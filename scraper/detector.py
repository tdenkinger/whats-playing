import re
import logging
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .models import Event, VenueConfig
from .venue_scraper import HEADERS, REQUEST_TIMEOUT, _scrape_json_ld, _scrape_css

logger = logging.getLogger(__name__)

MONTH_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b",
    re.IGNORECASE,
)
DATE_DIGIT_RE = re.compile(r"\d{1,2}")
EVENT_CLASS_RE = re.compile(
    r"event|show|concert|performance|gig|listing|card|ticket|act",
    re.IGNORECASE,
)
DATE_CLASS_RE = re.compile(r"date|time|when|day|schedule|calendar", re.IGNORECASE)
TITLE_CLASS_RE = re.compile(r"title|name|heading|act|artist|performer", re.IGNORECASE)
PRICE_CLASS_RE = re.compile(r"price|ticket|cost|admission|fare", re.IGNORECASE)
DOLLAR_RE = re.compile(r"\$\d+|\bfree\b", re.IGNORECASE)


@dataclass
class DetectionResult:
    success: bool
    strategy: str = "json-ld"
    event_selector: str = ""
    title_selector: str = ""
    date_selector: str = ""
    url_selector: str = ""
    description_selector: str = ""
    price_selector: str = ""
    image_selector: str = ""
    base_url: str = ""
    tockify_calendar: str = ""
    sample_events: list[Event] = field(default_factory=list)
    message: str = ""
    error: str = ""


def analyze_url(url: str, venue_name: str = "Preview") -> DetectionResult:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        return DetectionResult(success=False, error=f"Failed to fetch URL: {e}")

    soup = BeautifulSoup(resp.text, "lxml")
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    # Detect Tockify embedded calendar
    tockify_el = soup.find(attrs={"data-tockify-calendar": True})
    if tockify_el:
        calname = tockify_el.get("data-tockify-calendar", "")
        from .venue_scraper import _scrape_tockify
        sample = _scrape_tockify(VenueConfig(name=venue_name, url=url, strategy="tockify", tockify_calendar=calname))
        return DetectionResult(
            success=bool(sample),
            strategy="tockify",
            tockify_calendar=calname,
            sample_events=sample[:5],
            message=f"Found Tockify calendar '{calname}' — {len(sample)} upcoming events.",
        )

    dummy = VenueConfig(name=venue_name, url=url)
    json_ld_events = _scrape_json_ld(soup, dummy)
    if json_ld_events:
        return DetectionResult(
            success=True,
            strategy="json-ld",
            sample_events=json_ld_events[:5],
            message=f"Found {len(json_ld_events)} events via JSON-LD structured data.",
        )

    return _auto_detect_css(soup, url, base_url, venue_name)


def _auto_detect_css(
    soup: BeautifulSoup, url: str, base_url: str, venue_name: str
) -> DetectionResult:
    candidates = []
    for tag in ("article", "li", "div", "section"):
        for class_key, elements in _group_by_class(soup, tag).items():
            if len(elements) < 2:
                continue
            score = _score_candidate(elements, class_key)
            if score > 0:
                candidates.append((score, tag, class_key, elements))

    if not candidates:
        return DetectionResult(
            success=False,
            strategy="css",
            base_url=base_url,
            error=(
                "No repeating event-like elements found. "
                "Inspect the page source and enter CSS selectors manually."
            ),
        )

    candidates.sort(key=lambda x: x[0], reverse=True)
    _, tag, class_key, elements = candidates[0]

    first_class = class_key.split()[0]
    event_selector = f"{tag}.{first_class}"

    title_sel = _detect_child_selector(elements, _is_title)
    date_sel = _detect_child_selector(elements, _is_date)
    url_sel = _detect_url_selector(elements)
    price_sel = _detect_child_selector(elements, _is_price)

    test_venue = VenueConfig(
        name=venue_name,
        url=url,
        strategy="css",
        event_selector=event_selector,
        title_selector=title_sel,
        date_selector=date_sel,
        url_selector=url_sel,
        price_selector=price_sel,
        base_url=base_url,
    )
    events = _scrape_css(soup, test_venue)

    return DetectionResult(
        success=bool(events),
        strategy="css",
        event_selector=event_selector,
        title_selector=title_sel,
        date_selector=date_sel,
        url_selector=url_sel,
        price_selector=price_sel,
        base_url=base_url,
        sample_events=events[:5],
        message=(
            f"Auto-detected CSS selectors — found {len(events)} events."
            if events
            else "Selectors guessed but no events extracted — adjust manually."
        ),
    )


def _group_by_class(soup: BeautifulSoup, tag: str) -> dict[str, list]:
    groups: dict[str, list] = {}
    for el in soup.find_all(tag, class_=True):
        key = " ".join(el.get("class", []))
        groups.setdefault(key, []).append(el)
    return groups


def _score_candidate(elements: list, class_key: str) -> int:
    score = 0
    if EVENT_CLASS_RE.search(class_key):
        score += 10
    score += sum(3 for el in elements if MONTH_RE.search(el.get_text()))
    score += sum(1 for el in elements if el.find("a"))
    if 2 <= len(elements) <= 100:
        score += 2
    return score


def _detect_child_selector(elements: list, predicate) -> str:
    counts: dict[str, int] = {}
    for el in elements:
        for child in el.find_all(True):
            if predicate(child):
                sel = _best_selector(child)
                counts[sel] = counts.get(sel, 0) + 1
    if not counts:
        return ""
    return max(counts, key=counts.get)


def _best_selector(el) -> str:
    classes = el.get("class", [])
    return f".{classes[0]}" if classes else el.name


def _is_title(el) -> bool:
    if el.name in ("h1", "h2", "h3", "h4", "h5"):
        return True
    return bool(TITLE_CLASS_RE.search(" ".join(el.get("class", []))))


def _is_date(el) -> bool:
    classes = " ".join(el.get("class", []))
    if DATE_CLASS_RE.search(classes):
        return True
    text = el.get_text(strip=True)
    return bool(MONTH_RE.search(text) and DATE_DIGIT_RE.search(text) and len(text) < 60)


def _is_price(el) -> bool:
    classes = " ".join(el.get("class", []))
    text = el.get_text(strip=True)
    return bool(PRICE_CLASS_RE.search(classes)) or bool(DOLLAR_RE.search(text))


def _detect_url_selector(elements: list) -> str:
    if not any(el.find("a") for el in elements[:3]):
        return ""
    counts: dict[str, int] = {}
    for el in elements:
        for a in el.find_all("a"):
            classes = a.get("class", [])
            key = f"a.{classes[0]}" if classes else "a"
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return ""
    top = max(counts, key=counts.get)
    return top if counts[top] >= len(elements) * 0.4 else "a"
