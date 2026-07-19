from datetime import datetime

from scraper.models import Event


def test_sort_key_with_date():
    dt = datetime(2026, 6, 15, 20, 0)
    assert Event(venue_name="V", title="Jazz", date=dt).sort_key() == dt


def test_sort_key_without_date():
    assert Event(venue_name="V", title="Jazz", date=None).sort_key() == datetime.max


def test_sort_key_none_dates_sort_last():
    events = [
        Event(venue_name="V", title="No date", date=None),
        Event(venue_name="V", title="Early", date=datetime(2026, 6, 10)),
        Event(venue_name="V", title="Late", date=datetime(2026, 6, 20)),
    ]
    sorted_events = sorted(events, key=lambda e: e.sort_key())
    assert sorted_events[0].title == "Early"
    assert sorted_events[1].title == "Late"
    assert sorted_events[2].title == "No date"


def test_to_dict_from_dict_round_trip_with_date():
    event = Event(
        venue_name="V",
        title="Jazz",
        date=datetime(2026, 6, 15, 20, 0),
        url="https://example.com",
        price="$10",
    )
    assert Event.from_dict(event.to_dict()) == event


def test_to_dict_from_dict_round_trip_without_date():
    event = Event(venue_name="V", title="Jazz", date=None)
    d = event.to_dict()
    assert d["date"] is None
    assert Event.from_dict(d) == event
