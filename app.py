import logging
from datetime import datetime, date
from pathlib import Path

import streamlit as st

from scraper.models import Event
from scraper.venue_scraper import load_venues, scrape_all_venues

logging.basicConfig(level=logging.WARNING)

VENUES_CONFIG = Path(__file__).parent / "venues.yaml"
DATE_FORMAT = "%a, %b %-d %Y"
TIME_FORMAT = "%-I:%M %p"


def main():
    st.set_page_config(
        page_title="What's Playing",
        page_icon="🎵",
        layout="wide",
    )

    st.title("🎵 What's Playing")
    st.caption("Local music events aggregated from your configured venues.")

    # ── Sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Settings")

        if not VENUES_CONFIG.exists():
            st.error(f"Config not found: `{VENUES_CONFIG}`")
            st.stop()

        venues = load_venues(str(VENUES_CONFIG))

        if not venues:
            st.warning("No venues configured. Edit `venues.yaml` to add some.")
            st.stop()

        venue_names = [v.name for v in venues]
        selected_names = st.multiselect(
            "Venues",
            options=venue_names,
            default=venue_names,
        )

        st.divider()

        show_past = st.checkbox("Show past events", value=False)

        st.divider()

        refresh = st.button("🔄 Refresh events", use_container_width=True)

    # ── Scraping ─────────────────────────────────────────────────────────────
    selected_venues = [v for v in venues if v.name in selected_names]

    cache_key = "events"
    if refresh or cache_key not in st.session_state:
        st.session_state[cache_key] = _fetch_events(selected_venues)
        st.session_state["last_updated"] = datetime.now()
    elif set(selected_names) != set(st.session_state.get("_last_selected", [])):
        # Re-scrape when venue selection changes
        st.session_state[cache_key] = _fetch_events(selected_venues)
        st.session_state["last_updated"] = datetime.now()

    st.session_state["_last_selected"] = selected_names

    events: list[Event] = st.session_state[cache_key]

    if "last_updated" in st.session_state:
        st.caption(f"Last updated: {st.session_state['last_updated'].strftime('%Y-%m-%d %H:%M:%S')}")

    # ── Filter ────────────────────────────────────────────────────────────────
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if not show_past:
        events = [e for e in events if e.date is None or e.date >= today]

    # ── Display ───────────────────────────────────────────────────────────────
    if not events:
        st.info("No upcoming events found. Try refreshing or adding more venues in `venues.yaml`.")
        return

    st.write(f"**{len(events)} event{'s' if len(events) != 1 else ''}** found")

    _render_events(events)


def _fetch_events(selected_venues) -> list[Event]:
    progress_bar = st.progress(0, text="Starting scrape…")

    def on_progress(i: int, total: int, name: str):
        pct = int((i / total) * 100)
        progress_bar.progress(pct, text=f"Scraping {name}…")

    events = scrape_all_venues(selected_venues, progress_callback=on_progress)
    progress_bar.progress(100, text="Done!")
    progress_bar.empty()
    return events


def _render_events(events: list[Event]):
    # Group by date for a cleaner layout
    grouped: dict[str, list[Event]] = {}
    for event in events:
        if event.date:
            label = event.date.strftime(DATE_FORMAT)
        else:
            label = "Date Unknown"
        grouped.setdefault(label, []).append(event)

    for date_label, day_events in grouped.items():
        st.subheader(date_label)
        cols = st.columns(min(len(day_events), 3))
        for idx, event in enumerate(day_events):
            with cols[idx % 3]:
                _render_event_card(event)


def _render_event_card(event: Event):
    with st.container(border=True):
        if event.image_url:
            st.image(event.image_url, use_container_width=True)

        title = event.title or "Untitled Event"
        if event.url:
            st.markdown(f"### [{title}]({event.url})")
        else:
            st.markdown(f"### {title}")

        st.caption(f"📍 {event.venue_name}")

        if event.date:
            time_str = event.date.strftime(TIME_FORMAT) if event.date.hour or event.date.minute else ""
            if time_str:
                st.write(f"🕐 {time_str}")
        elif event.date_raw:
            st.write(f"📅 {event.date_raw}")

        if event.price:
            st.write(f"🎟 {event.price}")

        if event.description:
            with st.expander("Details"):
                st.write(event.description)


if __name__ == "__main__":
    main()
