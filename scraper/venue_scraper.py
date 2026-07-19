import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from .models import Event, VenueConfig

logger = logging.getLogger(__name__)


class VenueScrapeError(Exception):
    pass

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT = 15


def load_venues(config_path: str) -> list[VenueConfig]:
    with open(config_path) as f:
        data = yaml.safe_load(f)
    venues = []
    for v in data.get("venues", []):
        venues.append(
            VenueConfig(
                name=v["name"],
                url=v["url"],
                strategy=v.get("strategy", "json-ld"),
                event_selector=v.get("event_selector", ""),
                title_selector=v.get("title_selector", ""),
                date_selector=v.get("date_selector", ""),
                time_selector=v.get("time_selector", ""),
                url_selector=v.get("url_selector", ""),
                description_selector=v.get("description_selector", ""),
                price_selector=v.get("price_selector", ""),
                image_selector=v.get("image_selector", ""),
                base_url=v.get("base_url", ""),
                tockify_calendar=v.get("tockify_calendar", ""),
                viewcy_org=v.get("viewcy_org", ""),
                viewcy_category=v.get("viewcy_category", ""),
            )
        )
    return venues


def scrape_venue(venue: VenueConfig) -> list[Event]:
    if venue.strategy == "tockify":
        return _scrape_tockify(venue)
    if venue.strategy == "viewcy":
        return _scrape_viewcy(venue)

    try:
        resp = requests.get(venue.url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Failed to fetch %s: %s", venue.url, e)
        raise VenueScrapeError(str(e)) from e

    soup = BeautifulSoup(resp.text, "lxml")

    if venue.strategy == "json-ld":
        events = _scrape_json_ld(soup, venue)
        if events:
            return events
        # Fallback to CSS selectors if json-ld yields nothing and selectors exist
        if venue.event_selector:
            return _scrape_css(soup, venue)
        return []

    if venue.strategy == "css":
        return _scrape_css(soup, venue)

    logger.warning("Unknown strategy '%s' for venue %s", venue.strategy, venue.name)
    return []


def _scrape_tockify(venue: VenueConfig) -> list[Event]:
    calname = venue.tockify_calendar
    if not calname:
        logger.warning("No tockify_calendar set for venue %s", venue.name)
        return []

    now_ms = int(time.time() * 1000)
    api_url = f"https://tockify.com/api/ngevent?calname={calname}&max=50&startms={now_ms}"
    try:
        resp = requests.get(api_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("Failed to fetch Tockify calendar %s: %s", calname, e)
        raise VenueScrapeError(str(e)) from e

    events = []
    for e in data.get("events", []):
        title = e.get("content", {}).get("summary", {}).get("text", "")
        description = e.get("content", {}).get("description", {}).get("text", "")

        start_millis = e.get("when", {}).get("start", {}).get("millis")
        date = datetime.fromtimestamp(start_millis / 1000) if start_millis else None

        uid = e.get("eid", {}).get("uid", "")
        tid = e.get("eid", {}).get("tid", "")
        event_url = f"https://tockify.com/{calname}/detail/{uid}/{tid}" if uid and tid else ""

        events.append(Event(
            venue_name=venue.name,
            title=title,
            date=date,
            url=event_url,
            description=description,
        ))

    return events


def _scrape_viewcy(venue: VenueConfig) -> list[Event]:
    org = venue.viewcy_org
    if not org:
        logger.warning("No viewcy_org set for venue %s", venue.name)
        return []

    api_url = f"https://www.viewcy.com/api/o/{org}/courses"
    if venue.viewcy_category:
        api_url += f"?category_id={venue.viewcy_category}"
    try:
        resp = requests.get(api_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("Failed to fetch Viewcy org %s: %s", org, e)
        raise VenueScrapeError(str(e)) from e

    events = []
    for course in data.get("data", []):
        title = course.get("name", "").strip()
        book_url = course.get("url", "")

        tickets = course.get("tickets", [])
        price = ""
        if tickets:
            raw_price = tickets[0].get("price", "")
            try:
                val = float(raw_price)
                if val > 0:
                    price = f"${val:.0f}" if val == int(val) else f"${val:.2f}"
            except (ValueError, TypeError):
                pass

        for ev in course.get("events", []):
            starts_at = ev.get("starts_at", "")
            date = _parse_viewcy_date(starts_at)
            ev_url = ev.get("book_url", "") or book_url
            events.append(Event(
                venue_name=venue.name,
                title=title,
                date=date,
                date_raw=starts_at,
                url=ev_url,
                price=price,
            ))

    return events


def _parse_viewcy_date(starts_at: str) -> Optional[datetime]:
    if not starts_at:
        return None
    try:
        dt = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
        return dt.astimezone().replace(tzinfo=None)
    except (ValueError, OverflowError):
        return None


def _parse_date(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = dateparser.parse(raw, fuzzy=True)
        if dt is None:
            return None
        dt = dt.replace(tzinfo=None)
        # If the string has no 4-digit year and the date landed in the past,
        # assume next year — prevents December from misassigning January dates.
        if not re.search(r"\b\d{4}\b", raw) and dt < datetime.now() - timedelta(days=1):
            dt = dt.replace(year=dt.year + 1)
        return dt
    except (ValueError, OverflowError):
        return None


def _resolve_url(href: str, venue: VenueConfig) -> str:
    if not href:
        return ""
    base = venue.base_url or venue.url
    return urljoin(base, href)


def _scrape_json_ld(soup: BeautifulSoup, venue: VenueConfig) -> list[Event]:
    events: list[Event] = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        items = data if isinstance(data, list) else [data]
        for item in items:
            # Handle @graph wrapper
            if item.get("@type") == "ItemList" or "@graph" in item:
                items = item.get("@graph", item.get("itemListElement", []))
                continue
            if item.get("@type") not in ("Event", "MusicEvent", "Concert"):
                continue
            events.append(_json_ld_item_to_event(item, venue))

    return events


def _json_ld_item_to_event(item: dict, venue: VenueConfig) -> Event:
    name = item.get("name", "")
    start_raw = item.get("startDate", "")
    date = _parse_date(start_raw)
    url = item.get("url", "") or item.get("@id", "")
    description = item.get("description", "")
    image = item.get("image", "")
    if isinstance(image, dict):
        image = image.get("url", "")
    elif isinstance(image, list):
        image = image[0] if image else ""
        if isinstance(image, dict):
            image = image.get("url", "")

    offers = item.get("offers", {})
    price = ""
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if isinstance(offers, dict):
        price_val = offers.get("price", "")
        currency = offers.get("priceCurrency", "")
        if price_val:
            price = f"{currency}{price_val}".strip() if currency else str(price_val)

    return Event(
        venue_name=venue.name,
        title=name,
        date=date,
        date_raw=start_raw,
        url=_resolve_url(url, venue),
        description=description,
        image_url=image if isinstance(image, str) else "",
        price=price,
    )


def _scrape_css(soup: BeautifulSoup, venue: VenueConfig) -> list[Event]:
    if not venue.event_selector:
        logger.warning("No event_selector configured for venue %s", venue.name)
        return []

    events: list[Event] = []
    for block in soup.select(venue.event_selector):
        title = _text(block, venue.title_selector)
        date_raw = _text(block, venue.date_selector)
        if venue.time_selector:
            time_raw = _text(block, venue.time_selector)
            # Take only the start time (before any " - " or " – " range separator)
            start_time = time_raw.split(" - ")[0].split(" – ")[0].strip()
            if start_time:
                date_raw = f"{date_raw} {start_time}"
        date = _parse_date(date_raw)
        url = _attr(block, venue.url_selector, "href")
        description = _text(block, venue.description_selector)
        price = _text(block, venue.price_selector)
        image = _attr(block, venue.image_selector, "src")

        if not title:
            continue

        events.append(
            Event(
                venue_name=venue.name,
                title=title,
                date=date,
                date_raw=date_raw,
                url=_resolve_url(url, venue),
                description=description,
                image_url=_resolve_url(image, venue) if image else "",
                price=price,
            )
        )
    return events


def _text(block: BeautifulSoup, selector: str) -> str:
    if not selector:
        return ""
    el = block.select_one(selector)
    return el.get_text(strip=True) if el else ""


def _attr(block: BeautifulSoup, selector: str, attr: str) -> str:
    if not selector:
        return ""
    el = block.select_one(selector)
    return el.get(attr, "") if el else ""


def save_venues(config_path: str, venues: list[VenueConfig]) -> None:
    """Rewrite the venues list in the YAML file, preserving the documentation header."""
    with open(config_path) as f:
        content = f.read()

    import re as _re
    m = _re.search(r"^venues:", content, _re.MULTILINE)
    header = content[: m.end()] if m else "venues:"

    entries = []
    for v in venues:
        entry: dict = {"name": v.name, "url": v.url, "strategy": v.strategy}
        for attr in (
            "event_selector", "title_selector", "date_selector", "time_selector",
            "url_selector", "description_selector", "price_selector", "image_selector",
            "base_url", "tockify_calendar", "viewcy_org", "viewcy_category",
        ):
            val = getattr(v, attr)
            if val:
                entry[attr] = val
        entries.append(entry)

    raw = yaml.dump(entries, default_flow_style=False, sort_keys=False, allow_unicode=True)
    indented = "\n".join(f"  {line}" if line.strip() else "" for line in raw.splitlines())

    with open(config_path, "w") as f:
        f.write(header)
        f.write("\n")
        f.write(indented)
        f.write("\n")


def scrape_all_venues(
    venues: list[VenueConfig],
    progress_callback=None,
) -> tuple[list[Event], list[str]]:
    all_events: list[Event] = []
    failed: list[str] = []
    for i, venue in enumerate(venues):
        if progress_callback:
            progress_callback(i, len(venues), venue.name)
        try:
            all_events.extend(scrape_venue(venue))
        except VenueScrapeError:
            failed.append(venue.name)

    all_events.sort(key=lambda e: e.sort_key())
    return all_events, failed
