import json
from unittest.mock import MagicMock, patch

import pytest
import requests
from bs4 import BeautifulSoup

from scraper.detector import (
    DetectionResult,
    _best_selector,
    _detect_url_selector,
    _is_date,
    _is_price,
    _is_title,
    _score_candidate,
    analyze_url,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _el(html: str):
    # lxml wraps fragments in <html><body>; skip structural tags to get actual element
    soup = BeautifulSoup(html, "lxml")
    return soup.find(lambda tag: tag.name not in ("html", "head", "body"))


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _mock_response(html: str) -> MagicMock:
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status = MagicMock()
    return resp


def _json_ld_html(data) -> str:
    script = f'<script type="application/ld+json">{json.dumps(data)}</script>'
    return f"<html><head>{script}</head><body></body></html>"


_EVENT_CARDS_HTML = """
<html><body>
  <div class="event-card">
    <h2>Jazz Night</h2>
    <span class="date">June 15, 2026</span>
    <a href="/events/jazz">More info</a>
  </div>
  <div class="event-card">
    <h2>Blues Evening</h2>
    <span class="date">June 22, 2026</span>
    <a href="/events/blues">More info</a>
  </div>
  <div class="event-card">
    <h2>Rock Show</h2>
    <span class="date">June 29, 2026</span>
    <a href="/events/rock">More info</a>
  </div>
</body></html>
"""


# ── _is_title ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tag", ["h1", "h2", "h3", "h4", "h5"])
def test_is_title_heading_tags(tag):
    assert _is_title(_el(f"<{tag}>Jazz</{tag}>"))


@pytest.mark.parametrize("cls", ["event-title", "artist-name", "act-heading", "performer"])
def test_is_title_by_class(cls):
    assert _is_title(_el(f'<span class="{cls}">Jazz</span>'))


def test_is_title_negative():
    assert not _is_title(_el("<p>Some paragraph</p>"))
    assert not _is_title(_el('<span class="event-date">June 15</span>'))


# ── _is_date ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cls", ["event-date", "event-time", "show-day", "schedule", "calendar"])
def test_is_date_by_class(cls):
    assert _is_date(_el(f'<span class="{cls}">June 15</span>'))


def test_is_date_by_text_month_and_digit():
    assert _is_date(_el("<span>June 15, 2026</span>"))
    assert _is_date(_el("<span>Dec 31</span>"))


def test_is_date_requires_digit():
    assert not _is_date(_el("<span>June showcase</span>"))


def test_is_date_text_too_long():
    long = "Join us for our spectacular June event on the 15th at the main stage outdoor area"
    assert not _is_date(_el(f"<span>{long}</span>"))


def test_is_date_negative():
    assert not _is_date(_el("<p>Come enjoy live music nightly</p>"))


# ── _is_price ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cls", ["ticket-price", "cost", "admission", "fare"])
def test_is_price_by_class(cls):
    assert _is_price(_el(f'<span class="{cls}">$20</span>'))


def test_is_price_by_dollar_sign():
    assert _is_price(_el("<span>$20</span>"))
    assert _is_price(_el("<span>$5 at the door</span>"))


def test_is_price_free():
    assert _is_price(_el("<span>Free!</span>"))
    assert _is_price(_el("<span>FREE admission</span>"))


def test_is_price_negative():
    assert not _is_price(_el("<p>Come enjoy live music</p>"))


# ── _score_candidate ─────────────────────────────────────────────────────────

def test_score_event_class_bonus():
    soup = _soup("""
    <div class="event-listing"><h2>Jazz</h2><span>June 15</span></div>
    <div class="event-listing"><h2>Blues</h2><span>June 22</span></div>
    """)
    elements = soup.find_all("div", class_="event-listing")
    assert _score_candidate(elements, "event-listing") >= 10


def test_score_date_text_increases_score():
    with_dates = _soup("""
    <li class="card"><span>June 15, 2026</span></li>
    <li class="card"><span>July 4, 2026</span></li>
    """).find_all("li")
    without_dates = _soup("""
    <li class="card"><span>No date</span></li>
    <li class="card"><span>No date</span></li>
    """).find_all("li")

    assert _score_candidate(with_dates, "card") > _score_candidate(without_dates, "card")


def test_score_links_increase_score():
    with_links = _soup("""
    <div class="item"><a href="/1">Jazz</a></div>
    <div class="item"><a href="/2">Blues</a></div>
    """).find_all("div", class_="item")
    without_links = _soup("""
    <div class="item"><span>Jazz</span></div>
    <div class="item"><span>Blues</span></div>
    """).find_all("div", class_="item")

    assert _score_candidate(with_links, "item") > _score_candidate(without_links, "item")


# ── _best_selector ────────────────────────────────────────────────────────────

def test_best_selector_uses_first_class():
    el = _el('<div class="event-card extra">text</div>')
    assert _best_selector(el) == ".event-card"


def test_best_selector_no_class_uses_tag():
    el = _el("<article>text</article>")
    assert _best_selector(el) == "article"


# ── _detect_url_selector ─────────────────────────────────────────────────────

def test_detect_url_no_links_returns_empty():
    elements = _soup("""
    <div class="card"><h2>Jazz</h2></div>
    <div class="card"><h2>Blues</h2></div>
    <div class="card"><h2>Rock</h2></div>
    """).find_all("div", class_="card")
    assert _detect_url_selector(elements) == ""


def test_detect_url_plain_links():
    elements = _soup("""
    <div class="card"><a href="/1">Jazz</a></div>
    <div class="card"><a href="/2">Blues</a></div>
    <div class="card"><a href="/3">Rock</a></div>
    """).find_all("div", class_="card")
    assert _detect_url_selector(elements) == "a"


def test_detect_url_classed_links():
    elements = _soup("""
    <div class="card"><a class="btn" href="/1">Jazz</a></div>
    <div class="card"><a class="btn" href="/2">Blues</a></div>
    <div class="card"><a class="btn" href="/3">Rock</a></div>
    """).find_all("div", class_="card")
    assert _detect_url_selector(elements) == "a.btn"


# ── analyze_url ───────────────────────────────────────────────────────────────

def test_analyze_url_detects_json_ld():
    html = _json_ld_html({"@type": "Event", "name": "Jazz Night", "startDate": "2026-06-15T20:00:00"})
    with patch("scraper.detector.requests.get", return_value=_mock_response(html)):
        result = analyze_url("https://example.com/events")

    assert result.success
    assert result.strategy == "json-ld"
    assert len(result.sample_events) == 1
    assert result.sample_events[0].title == "Jazz Night"


def test_analyze_url_falls_back_to_css():
    with patch("scraper.detector.requests.get", return_value=_mock_response(_EVENT_CARDS_HTML)):
        result = analyze_url("https://example.com/events")

    assert result.strategy == "css"
    assert result.event_selector != ""
    assert result.title_selector != ""


def test_analyze_url_css_finds_events():
    with patch("scraper.detector.requests.get", return_value=_mock_response(_EVENT_CARDS_HTML)):
        result = analyze_url("https://example.com/events")

    assert result.success
    assert len(result.sample_events) > 0


def test_analyze_url_http_error():
    with patch("scraper.detector.requests.get", side_effect=requests.RequestException("timeout")):
        result = analyze_url("https://example.com/events")

    assert not result.success
    assert "Failed to fetch" in result.error


def test_analyze_url_no_events_found():
    html = "<html><body><p>Nothing here</p></body></html>"
    with patch("scraper.detector.requests.get", return_value=_mock_response(html)):
        result = analyze_url("https://example.com/events")

    assert not result.success


def test_analyze_url_json_ld_limits_sample_to_five():
    data = [{"@type": "Event", "name": f"Event {i}", "startDate": f"2026-06-{i+10:02d}"} for i in range(10)]
    html = _json_ld_html(data)
    with patch("scraper.detector.requests.get", return_value=_mock_response(html)):
        result = analyze_url("https://example.com/events")

    assert result.success
    assert len(result.sample_events) <= 5
