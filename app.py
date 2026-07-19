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
        st.session_state[cache_key], st.session_state["failed_venues"] = _fetch_events(selected_venues)
        st.session_state["last_updated"] = datetime.now()
    elif set(selected_names) != set(st.session_state.get("_last_selected", [])):
        # Re-scrape when venue selection changes
        st.session_state[cache_key], st.session_state["failed_venues"] = _fetch_events(selected_venues)
        st.session_state["last_updated"] = datetime.now()

    st.session_state["_last_selected"] = selected_names

    events: list[Event] = st.session_state[cache_key]

    if "last_updated" in st.session_state:
        st.caption(f"Last updated: {st.session_state['last_updated'].strftime('%Y-%m-%d %H:%M:%S')}")

    failed = st.session_state.get("failed_venues", [])
    if failed:
        st.warning(f"Could not reach: {', '.join(failed)}")

    # ── Filter ────────────────────────────────────────────────────────────────
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if not show_past:
        events = [e for e in events if e.date is None or e.date >= today]

    # ── Display ───────────────────────────────────────────────────────────────
    if not events:
        st.info("No upcoming events found. Try refreshing or adding more venues in `venues.yaml`.")
        return

    st.write(f"**{len(events)} event{'s' if len(events) != 1 else ''}** found")

    venue_urls = {v.name: v.url for v in venues}
    _render_events(events, venue_urls)


def _fetch_events(selected_venues) -> tuple[list[Event], list[str]]:
    progress_bar = st.progress(0, text="Starting scrape…")

    def on_progress(i: int, total: int, name: str):
        pct = int((i / total) * 100)
        progress_bar.progress(pct, text=f"Scraping {name}…")

    events, failed = scrape_all_venues(selected_venues, progress_callback=on_progress)
    progress_bar.progress(100, text="Done!")
    progress_bar.empty()
    return events, failed


def _render_events(events: list[Event], venue_urls: dict[str, str]):
    by_date: dict[str, dict[str, list[Event]]] = {}
    for event in events:
        date_label = event.date.strftime(DATE_FORMAT) if event.date else "Date Unknown"
        by_date.setdefault(date_label, {}).setdefault(event.venue_name, []).append(event)

    for date_label, venues in by_date.items():
        st.subheader(date_label)
        for venue_name, venue_events in sorted(venues.items()):
            url = venue_urls.get(venue_name, "")
            venue_heading = f"**[{venue_name}]({url})**" if url else f"**{venue_name}**"
            st.markdown(venue_heading)
            lines = []
            for event in venue_events:
                title = event.title or "Untitled Event"
                time_str = f" · {event.date.strftime(TIME_FORMAT)}" if event.date and (event.date.hour or event.date.minute) else ""
                price_str = f" · {event.price}" if event.price else ""
                link = f"[{title}]({event.url})" if event.url else title
                lines.append(f"- {link}{time_str}{price_str}")
            st.markdown("\n".join(lines))


if __name__ == "__main__":
    main()
