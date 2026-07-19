import json
import textwrap
from datetime import datetime
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup

from scraper.models import Event, VenueConfig
from scraper.venue_scraper import (
    _parse_date,
    _resolve_url,
    _scrape_css,
    _scrape_json_ld,
    load_venues,
    save_venues,
    scrape_all_venues,
    scrape_venue,
    VenueScrapeError,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _json_ld_soup(data) -> BeautifulSoup:
    script = f'<script type="application/ld+json">{json.dumps(data)}</script>'
    return _soup(f"<html><head>{script}</head><body></body></html>")


_VENUE = VenueConfig(name="Test", url="https://example.com/events")


# ── _parse_date ───────────────────────────────────────────────────────────────

def test_parse_date_empty_string():
    assert _parse_date("") is None


def test_parse_date_returns_none_for_gibberish():
    # fuzzy parser raises ValueError on total gibberish
    result = _parse_date("xyzzy frobnicator")
    assert result is None


def test_parse_date_iso():
    result = _parse_date("2026-06-15T20:00:00")
    assert result is not None
    assert result.year == 2026
    assert result.month == 6
    assert result.day == 15
    assert result.hour == 20
    assert result.tzinfo is None


def test_parse_date_strips_timezone():
    result = _parse_date("2026-06-15T20:00:00-08:00")
    assert result is not None
    assert result.tzinfo is None


def test_parse_date_human_readable():
    result = _parse_date("June 15, 2026")
    assert result is not None
    assert result.year == 2026
    assert result.month == 6
    assert result.day == 15


def test_parse_date_yearless_past_date_bumped():
    # A month/day that already passed this year should be bumped to next year
    result = _parse_date("January 1")
    assert result is not None
    assert result.year > datetime.now().year or result.month > 1


def test_parse_date_with_4digit_year_not_bumped():
    # Explicit year must never be overridden even if the date is in the past
    result = _parse_date("January 1, 2020")
    assert result is not None
    assert result.year == 2020


# ── _resolve_url ──────────────────────────────────────────────────────────────

def test_resolve_url_empty():
    assert _resolve_url("", _VENUE) == ""


def test_resolve_url_absolute_unchanged():
    assert _resolve_url("https://other.com/event/1", _VENUE) == "https://other.com/event/1"


def test_resolve_url_relative_against_venue_url():
    assert _resolve_url("/event/1", _VENUE) == "https://example.com/event/1"


def test_resolve_url_relative_prefers_base_url():
    venue = VenueConfig(name="V", url="https://example.com/events", base_url="https://base.com")
    assert _resolve_url("/event/1", venue) == "https://base.com/event/1"


# ── load_venues ───────────────────────────────────────────────────────────────

_MINIMAL_YAML = textwrap.dedent("""\
    venues:
      - name: Test Venue
        url: https://example.com/events
        strategy: json-ld
      - name: CSS Venue
        url: https://other.com/shows
        strategy: css
        event_selector: .event-card
        title_selector: h2
        date_selector: .date
        url_selector: a
        base_url: https://other.com
""")


def test_load_venues_parses_all_fields(tmp_path):
    config = tmp_path / "venues.yaml"
    config.write_text(_MINIMAL_YAML)
    venues = load_venues(str(config))

    assert len(venues) == 2
    assert venues[0].name == "Test Venue"
    assert venues[0].strategy == "json-ld"
    assert venues[1].event_selector == ".event-card"
    assert venues[1].base_url == "https://other.com"


def test_load_venues_optional_fields_default_empty(tmp_path):
    config = tmp_path / "venues.yaml"
    config.write_text("venues:\n  - name: V\n    url: https://x.com\n    strategy: json-ld\n")
    venues = load_venues(str(config))

    assert venues[0].event_selector == ""
    assert venues[0].base_url == ""


def test_load_venues_missing_venues_key(tmp_path):
    config = tmp_path / "venues.yaml"
    config.write_text("other_key: value\n")
    assert load_venues(str(config)) == []


# ── save_venues ───────────────────────────────────────────────────────────────

def test_save_load_roundtrip(tmp_path):
    config = tmp_path / "venues.yaml"
    config.write_text("venues:\n")
    originals = [
        VenueConfig(name="Venue A", url="https://a.com/events", strategy="json-ld"),
        VenueConfig(
            name="Venue B",
            url="https://b.com/shows",
            strategy="css",
            event_selector=".event",
            title_selector="h2",
            date_selector=".date",
            url_selector="a",
            price_selector=".price",
            base_url="https://b.com",
        ),
    ]
    save_venues(str(config), originals)
    loaded = load_venues(str(config))

    assert len(loaded) == 2
    assert loaded[0].name == "Venue A"
    assert loaded[0].strategy == "json-ld"
    assert loaded[1].event_selector == ".event"
    assert loaded[1].price_selector == ".price"
    assert loaded[1].base_url == "https://b.com"


def test_save_venues_preserves_header_comments(tmp_path):
    config = tmp_path / "venues.yaml"
    config.write_text("# Documentation header\n# Line two\nvenues:\n")

    save_venues(str(config), [VenueConfig(name="New", url="https://new.com")])
    content = config.read_text()

    assert content.startswith("# Documentation header")
    assert "New" in content


def test_save_venues_omits_empty_optional_fields(tmp_path):
    config = tmp_path / "venues.yaml"
    config.write_text("venues:\n")
    save_venues(str(config), [VenueConfig(name="V", url="https://v.com")])
    content = config.read_text()

    assert "event_selector" not in content
    assert "base_url" not in content


def test_save_venues_handles_apostrophe_in_name(tmp_path):
    config = tmp_path / "venues.yaml"
    config.write_text("venues:\n")
    save_venues(str(config), [VenueConfig(name="Fred's Bar", url="https://freds.com")])
    assert load_venues(str(config))[0].name == "Fred's Bar"


def test_save_venues_overwrites_existing_list(tmp_path):
    config = tmp_path / "venues.yaml"
    config.write_text("venues:\n")
    save_venues(str(config), [VenueConfig(name="Old", url="https://old.com")])
    save_venues(str(config), [VenueConfig(name="New", url="https://new.com")])
    loaded = load_venues(str(config))

    assert len(loaded) == 1
    assert loaded[0].name == "New"


def test_save_venues_ignores_commented_venues_key(tmp_path):
    # Regression: a "# venues:" in the comment block must not confuse header extraction
    header = "# Example:\n# venues:\n#   - name: x\nvenues:\n"
    config = tmp_path / "venues.yaml"
    config.write_text(header)
    save_venues(str(config), [VenueConfig(name="Real", url="https://real.com")])
    loaded = load_venues(str(config))

    assert len(loaded) == 1
    assert loaded[0].name == "Real"


# ── _scrape_json_ld ───────────────────────────────────────────────────────────

def test_json_ld_event():
    soup = _json_ld_soup({"@type": "Event", "name": "Jazz Night", "startDate": "2026-06-15T20:00:00"})
    events = _scrape_json_ld(soup, _VENUE)

    assert len(events) == 1
    assert events[0].title == "Jazz Night"
    assert events[0].date is not None
    assert events[0].date.year == 2026


def test_json_ld_music_event():
    soup = _json_ld_soup({"@type": "MusicEvent", "name": "Blues Night"})
    assert len(_scrape_json_ld(soup, _VENUE)) == 1


def test_json_ld_concert():
    soup = _json_ld_soup({"@type": "Concert", "name": "Rock Show"})
    assert len(_scrape_json_ld(soup, _VENUE)) == 1


def test_json_ld_wrong_type_skipped():
    soup = _json_ld_soup({"@type": "LocalBusiness", "name": "A Bar"})
    assert _scrape_json_ld(soup, _VENUE) == []


def test_json_ld_array_of_events():
    data = [
        {"@type": "Event", "name": "Event A", "startDate": "2026-06-15"},
        {"@type": "Event", "name": "Event B", "startDate": "2026-06-16"},
    ]
    events = _scrape_json_ld(_json_ld_soup(data), _VENUE)
    assert len(events) == 2
    assert {e.title for e in events} == {"Event A", "Event B"}


def test_json_ld_price_with_currency():
    data = {"@type": "Event", "name": "Jazz", "offers": {"price": "20", "priceCurrency": "USD"}}
    events = _scrape_json_ld(_json_ld_soup(data), _VENUE)
    assert events[0].price == "USD20"


def test_json_ld_price_without_currency():
    data = {"@type": "Event", "name": "Jazz", "offers": {"price": "20"}}
    events = _scrape_json_ld(_json_ld_soup(data), _VENUE)
    assert events[0].price == "20"


def test_json_ld_price_list_offers():
    data = {"@type": "Event", "name": "Jazz", "offers": [{"price": "15", "priceCurrency": "USD"}]}
    events = _scrape_json_ld(_json_ld_soup(data), _VENUE)
    assert events[0].price == "USD15"


def test_json_ld_image_string():
    data = {"@type": "Event", "name": "Jazz", "image": "https://example.com/img.jpg"}
    events = _scrape_json_ld(_json_ld_soup(data), _VENUE)
    assert events[0].image_url == "https://example.com/img.jpg"


def test_json_ld_image_dict():
    data = {"@type": "Event", "name": "Jazz", "image": {"url": "https://example.com/img.jpg"}}
    events = _scrape_json_ld(_json_ld_soup(data), _VENUE)
    assert events[0].image_url == "https://example.com/img.jpg"


def test_json_ld_url_fallback_to_id():
    data = {"@type": "Event", "name": "Jazz", "@id": "https://example.com/event/1"}
    events = _scrape_json_ld(_json_ld_soup(data), _VENUE)
    assert events[0].url == "https://example.com/event/1"


def test_json_ld_invalid_json_skipped():
    html = '<html><head><script type="application/ld+json">not json!</script></head><body></body></html>'
    assert _scrape_json_ld(_soup(html), _VENUE) == []


def test_json_ld_no_scripts():
    assert _scrape_json_ld(_soup("<html><body></body></html>"), _VENUE) == []


# ── _scrape_css ───────────────────────────────────────────────────────────────

_CSS_HTML = """
<html><body>
  <div class="event-card">
    <h2>Jazz Night</h2>
    <span class="event-date">June 15, 2026</span>
    <a href="/events/jazz">More info</a>
    <span class="price">$20</span>
  </div>
  <div class="event-card">
    <h2>Blues Evening</h2>
    <span class="event-date">June 22, 2026</span>
    <a href="/events/blues">More info</a>
    <span class="price">$15</span>
  </div>
</body></html>
"""

_CSS_VENUE = VenueConfig(
    name="Test",
    url="https://example.com/events",
    strategy="css",
    event_selector=".event-card",
    title_selector="h2",
    date_selector=".event-date",
    url_selector="a",
    price_selector=".price",
    base_url="https://example.com",
)


def test_scrape_css_extracts_all_events():
    events = _scrape_css(_soup(_CSS_HTML), _CSS_VENUE)
    assert len(events) == 2


def test_scrape_css_title_and_price():
    events = _scrape_css(_soup(_CSS_HTML), _CSS_VENUE)
    assert events[0].title == "Jazz Night"
    assert events[0].price == "$20"


def test_scrape_css_resolves_relative_url():
    events = _scrape_css(_soup(_CSS_HTML), _CSS_VENUE)
    assert events[0].url == "https://example.com/events/jazz"


def test_scrape_css_parses_date():
    events = _scrape_css(_soup(_CSS_HTML), _CSS_VENUE)
    assert events[0].date is not None
    assert events[0].date.month == 6
    assert events[0].date.day == 15


def test_scrape_css_no_event_selector_returns_empty():
    venue = VenueConfig(name="V", url="https://example.com", strategy="css", event_selector="")
    assert _scrape_css(_soup(_CSS_HTML), venue) == []


def test_scrape_css_skips_blocks_without_title():
    html = """
    <html><body>
      <div class="event-card"><span class="event-date">June 15, 2026</span></div>
    </body></html>
    """
    venue = VenueConfig(
        name="V", url="https://example.com", strategy="css",
        event_selector=".event-card", title_selector="h2",
    )
    assert _scrape_css(_soup(html), venue) == []


# ── scrape_all_venues ─────────────────────────────────────────────────────────

def test_scrape_all_venues_sorts_by_date():
    venues = [VenueConfig(name="A", url="https://a.com"), VenueConfig(name="B", url="https://b.com")]
    later = Event(venue_name="A", title="Later", date=datetime(2026, 6, 20))
    earlier = Event(venue_name="B", title="Earlier", date=datetime(2026, 6, 10))

    with patch("scraper.venue_scraper.scrape_venue", side_effect=[[later], [earlier]]):
        events, failed = scrape_all_venues(venues)

    assert events[0].title == "Earlier"
    assert events[1].title == "Later"
    assert failed == []


def test_scrape_all_venues_calls_progress_callback():
    venues = [VenueConfig(name="V1", url="https://v1.com"), VenueConfig(name="V2", url="https://v2.com")]
    calls = []

    with patch("scraper.venue_scraper.scrape_venue", return_value=[]):
        scrape_all_venues(venues, progress_callback=lambda i, total, name: calls.append((i, total, name)))

    assert calls == [(0, 2, "V1"), (1, 2, "V2")]


def test_scrape_all_venues_none_callback_ok():
    with patch("scraper.venue_scraper.scrape_venue", return_value=[]):
        events, failed = scrape_all_venues([VenueConfig(name="V", url="https://v.com")])
    assert events == []
    assert failed == []


def test_scrape_all_venues_tracks_failed_venues():
    venues = [
        VenueConfig(name="Good", url="https://good.com"),
        VenueConfig(name="Bad", url="https://bad.com"),
    ]
    good_event = Event(venue_name="Good", title="Show", date=datetime(2026, 6, 15))

    def fake_scrape(venue):
        if venue.name == "Bad":
            raise VenueScrapeError("timeout")
        return [good_event]

    with patch("scraper.venue_scraper.scrape_venue", side_effect=fake_scrape):
        events, failed = scrape_all_venues(venues)

    assert len(events) == 1
    assert failed == ["Bad"]


def test_scrape_venue_raises_on_network_error():
    import requests as _requests
    venue = VenueConfig(name="V", url="https://example.com/events")
    with patch("scraper.venue_scraper.requests.get", side_effect=_requests.ConnectionError("refused")):
        with pytest.raises(VenueScrapeError):
            scrape_venue(venue)
