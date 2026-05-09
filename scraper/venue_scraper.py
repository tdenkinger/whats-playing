import json
import logging
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

from .models import Event, VenueConfig

logger = logging.getLogger(__name__)

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
                url_selector=v.get("url_selector", ""),
                description_selector=v.get("description_selector", ""),
                price_selector=v.get("price_selector", ""),
                image_selector=v.get("image_selector", ""),
                base_url=v.get("base_url", ""),
            )
        )
    return venues


def scrape_venue(venue: VenueConfig) -> list[Event]:
    try:
        resp = requests.get(venue.url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Failed to fetch %s: %s", venue.url, e)
        return []

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


def _parse_date(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return dateparser.parse(raw, fuzzy=True)
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


def scrape_all_venues(
    venues: list[VenueConfig],
    progress_callback=None,
) -> list[Event]:
    all_events: list[Event] = []
    for i, venue in enumerate(venues):
        if progress_callback:
            progress_callback(i, len(venues), venue.name)
        events = scrape_venue(venue)
        all_events.extend(events)

    all_events.sort(key=lambda e: e.sort_key())
    return all_events
