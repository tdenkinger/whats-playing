import streamlit as st

from auth import logout_button, require_password
from config import VENUES_CONFIG
from scraper.models import VenueConfig
from scraper.venue_scraper import load_venues, save_venues, scrape_venue, VenueScrapeError
from scraper.detector import analyze_url, DetectionResult

DATE_FORMAT = "%a, %b %-d %Y"
TIME_FORMAT = "%-I:%M %p"

SELECTOR_FIELDS = (
    "event_selector",
    "title_selector",
    "date_selector",
    "time_selector",
    "url_selector",
    "description_selector",
    "price_selector",
    "image_selector",
    "base_url",
)
TOCKIFY_FIELD = "tockify_calendar"
VIEWCY_FIELDS = ("viewcy_org", "viewcy_category")

SELECTOR_LABELS = {
    "event_selector": "event_selector *(required)*",
    "time_selector": "time_selector",
    "title_selector": "title_selector",
    "date_selector": "date_selector",
    "url_selector": "url_selector",
    "description_selector": "description_selector",
    "price_selector": "price_selector",
    "image_selector": "image_selector",
    "base_url": "base_url",
}

SELECTOR_HELP = {
    "event_selector": "Matches each event block on the page.",
    "time_selector": "Optional separate element for the show time. Its start time is appended to the date before parsing.",
    "base_url": "Used to resolve relative URLs. Defaults to the events page URL.",
}


def _state(key: str, default="") -> str:
    return st.session_state.get(key, default)


def _load_venue_into_state(venue: VenueConfig | None) -> None:
    st.session_state["ve_name"] = venue.name if venue else ""
    st.session_state["ve_url"] = venue.url if venue else ""
    st.session_state["ve_strategy"] = venue.strategy if venue else "json-ld"
    for attr in SELECTOR_FIELDS:
        st.session_state[f"ve_{attr}"] = getattr(venue, attr, "") if venue else ""
    st.session_state["ve_tockify_calendar"] = venue.tockify_calendar if venue else ""
    st.session_state["ve_viewcy_org"] = venue.viewcy_org if venue else ""
    st.session_state["ve_viewcy_category"] = venue.viewcy_category if venue else ""
    st.session_state.pop("ve_detection", None)
    st.session_state.pop("ve_test_events", None)
    st.session_state.pop("ve_test_error", None)


def main():
    st.set_page_config(page_title="Venue Editor", page_icon="🎸", layout="wide")
    require_password()
    logout_button()
    st.title("🎸 Venue Editor")

    if not VENUES_CONFIG.exists():
        st.error(f"Config not found: `{VENUES_CONFIG}`")
        return

    venues = load_venues(str(VENUES_CONFIG))

    # ── Mode + venue selection ───────────────────────────────────────────────
    mode = st.radio("", ["Add new venue", "Edit existing venue"], horizontal=True)

    venue: VenueConfig | None = None
    if mode == "Edit existing venue":
        if not venues:
            st.info("No venues configured yet. Switch to 'Add new venue' to create one.")
            return
        sel_name = st.selectbox("Select venue", [v.name for v in venues])
        venue = next(v for v in venues if v.name == sel_name)

    # Load state when the selected venue changes
    current_key = f"edit:{venue.name}" if venue else "new"
    if st.session_state.get("ve_loaded") != current_key:
        _load_venue_into_state(venue)
        st.session_state["ve_loaded"] = current_key

    st.divider()

    # ── Two-column layout ────────────────────────────────────────────────────
    form_col, preview_col = st.columns([3, 2])

    with form_col:
        _render_form(venues, venue, mode)

    with preview_col:
        _render_preview()


def _render_form(all_venues: list[VenueConfig], venue: VenueConfig | None, mode: str) -> None:
    # Name + URL
    st.text_input("Venue name", key="ve_name")

    url_col, btn_col = st.columns([4, 1])
    with url_col:
        st.text_input("Events page URL", key="ve_url")
    with btn_col:
        st.write("")
        st.write("")
        analyze_clicked = st.button(
            "🔍 Analyze",
            use_container_width=True,
            disabled=not st.session_state.get("ve_url", "").strip(),
        )

    if analyze_clicked:
        url = st.session_state["ve_url"].strip()
        name = st.session_state.get("ve_name", "Preview").strip() or "Preview"
        with st.spinner("Fetching and analyzing page…"):
            result: DetectionResult = analyze_url(url, name)
        st.session_state["ve_detection"] = result
        st.session_state.pop("ve_test_events", None)
        if result.success:
            st.session_state["ve_strategy"] = result.strategy
            for attr in SELECTOR_FIELDS:
                st.session_state[f"ve_{attr}"] = getattr(result, attr, "")
            st.session_state["ve_tockify_calendar"] = result.tockify_calendar
        st.rerun()

    detection: DetectionResult | None = st.session_state.get("ve_detection")
    if detection:
        if detection.error:
            st.error(detection.error)
        elif detection.message:
            st.success(detection.message)

    # Strategy
    strategy_options = ["json-ld", "css", "tockify", "viewcy"]
    current_strategy = st.session_state.get("ve_strategy", "json-ld")
    st.radio(
        "Scraping strategy",
        strategy_options,
        index=strategy_options.index(current_strategy) if current_strategy in strategy_options else 0,
        horizontal=True,
        key="ve_strategy",
        help=(
            "**json-ld**: extracts structured data embedded in the page (most modern sites). "
            "**css**: uses CSS selectors to find event elements. "
            "**tockify**: queries the Tockify API for sites using a Tockify calendar embed."
        ),
    )

    # Strategy-specific fields
    if st.session_state.get("ve_strategy") == "tockify":
        st.text_input(
            "Tockify calendar name",
            key="ve_tockify_calendar",
            help="The value of `data-tockify-calendar` in the page source. Auto-filled by Analyze.",
        )

    elif st.session_state.get("ve_strategy") == "viewcy":
        st.text_input(
            "Viewcy organization slug",
            key="ve_viewcy_org",
            help="The organization slug from the Viewcy URL, e.g. `jalopytheatre`.",
        )
        st.text_input(
            "Viewcy category ID (optional)",
            key="ve_viewcy_category",
            help="Filter by category ID, e.g. `360` for performances. Leave blank to fetch all.",
        )

    elif st.session_state.get("ve_strategy") == "css":
        st.markdown("**CSS Selectors**")
        st.caption(
            "All selectors except `event_selector` are evaluated within each matched event block."
        )
        left, right = st.columns(2)
        fields = list(SELECTOR_FIELDS)
        for i, attr in enumerate(fields):
            col = left if i % 2 == 0 else right
            with col:
                st.text_input(
                    SELECTOR_LABELS[attr],
                    key=f"ve_{attr}",
                    help=SELECTOR_HELP.get(attr),
                )

    st.divider()

    # Save / Delete
    save_col, delete_col = st.columns([3, 1])
    with save_col:
        strategy = st.session_state.get("ve_strategy", "json-ld")
        name = st.session_state.get("ve_name", "").strip()
        url = st.session_state.get("ve_url", "").strip()
        event_selector = st.session_state.get("ve_event_selector", "").strip()

        tockify_calendar = st.session_state.get("ve_tockify_calendar", "").strip()
        viewcy_org = st.session_state.get("ve_viewcy_org", "").strip()

        can_save = bool(name and url)
        if strategy == "css":
            can_save = can_save and bool(event_selector)
        elif strategy == "tockify":
            can_save = can_save and bool(tockify_calendar)
        elif strategy == "viewcy":
            can_save = can_save and bool(viewcy_org)

        if st.button("💾 Save venue", type="primary", use_container_width=True, disabled=not can_save):
            _save(all_venues, venue, mode)

    with delete_col:
        if mode == "Edit existing venue" and venue:
            if st.button("🗑 Delete", use_container_width=True):
                updated = [v for v in all_venues if v.name != venue.name]
                save_venues(str(VENUES_CONFIG), updated)
                st.session_state.pop("ve_loaded", None)
                st.success(f"Deleted '{venue.name}'.")
                st.rerun()


def _save(all_venues: list[VenueConfig], venue: VenueConfig | None, mode: str) -> None:
    strategy = st.session_state.get("ve_strategy", "json-ld")
    name = st.session_state.get("ve_name", "").strip()
    url = st.session_state.get("ve_url", "").strip()

    new_venue = VenueConfig(
        name=name,
        url=url,
        strategy=strategy,
        **{
            attr: (st.session_state.get(f"ve_{attr}", "").strip() if strategy == "css" else "")
            for attr in SELECTOR_FIELDS
        },
        tockify_calendar=st.session_state.get("ve_tockify_calendar", "").strip() if strategy == "tockify" else "",
        viewcy_org=st.session_state.get("ve_viewcy_org", "").strip() if strategy == "viewcy" else "",
        viewcy_category=st.session_state.get("ve_viewcy_category", "").strip() if strategy == "viewcy" else "",
    )

    updated = list(all_venues)
    if mode == "Edit existing venue" and venue:
        idx = next(i for i, v in enumerate(updated) if v.name == venue.name)
        updated[idx] = new_venue
    else:
        if any(v.name == name for v in updated):
            st.error(f"A venue named '{name}' already exists.")
            return
        updated.append(new_venue)

    save_venues(str(VENUES_CONFIG), updated)
    st.session_state["ve_loaded"] = f"edit:{name}"
    st.session_state.pop("ve_test_events", None)
    st.session_state.pop("ve_detection", None)
    st.success(f"Saved '{name}'.")
    st.rerun()


def _render_preview() -> None:
    st.subheader("Preview")

    url = st.session_state.get("ve_url", "").strip()
    strategy = st.session_state.get("ve_strategy", "json-ld")

    test_venue = VenueConfig(
        name=st.session_state.get("ve_name", "Preview").strip() or "Preview",
        url=url,
        strategy=strategy,
        **{
            attr: (st.session_state.get(f"ve_{attr}", "").strip() if strategy == "css" else "")
            for attr in SELECTOR_FIELDS
        },
        tockify_calendar=st.session_state.get("ve_tockify_calendar", "").strip() if strategy == "tockify" else "",
        viewcy_org=st.session_state.get("ve_viewcy_org", "").strip() if strategy == "viewcy" else "",
        viewcy_category=st.session_state.get("ve_viewcy_category", "").strip() if strategy == "viewcy" else "",
    )

    if st.button("▶ Test scrape", use_container_width=True, disabled=not url):
        with st.spinner("Scraping…"):
            try:
                events = scrape_venue(test_venue)
                st.session_state["ve_test_events"] = events
                st.session_state.pop("ve_test_error", None)
            except VenueScrapeError as exc:
                st.session_state["ve_test_error"] = str(exc)
                st.session_state.pop("ve_test_events", None)
        st.rerun()

    if err := st.session_state.get("ve_test_error"):
        st.error(f"Scrape failed: {err}")
        return

    # Prefer explicit test results; fall back to detection sample
    detection: DetectionResult | None = st.session_state.get("ve_detection")
    events = st.session_state.get("ve_test_events")
    if events is None and detection and detection.sample_events:
        events = detection.sample_events
        st.caption("Showing sample from URL analysis — click **▶ Test scrape** for full results.")

    if events is None:
        st.info("Click **🔍 Analyze** or **▶ Test scrape** to see a preview.")
        return

    if not events:
        st.warning("No events found with current settings.")
        return

    st.write(f"**{len(events)} event(s)**")
    for event in events[:10]:
        with st.container(border=True):
            title = event.title or "Untitled Event"
            st.markdown(f"**[{title}]({event.url})**" if event.url else f"**{title}**")
            if event.date:
                fmt = f"{DATE_FORMAT} · {TIME_FORMAT}" if (event.date.hour or event.date.minute) else DATE_FORMAT
                st.caption(event.date.strftime(fmt))
            elif event.date_raw:
                st.caption(event.date_raw)
            if event.price:
                st.caption(f"Price: {event.price}")


if __name__ == "__main__":
    main()
