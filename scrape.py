"""Scrape all configured venues and write results to data/events.json.

Run by the GitHub Actions daily schedule (.github/workflows/scrape.yml)
so the deployed app can serve pre-scraped data instead of hitting venue
sites on every page load.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from scraper.venue_scraper import load_venues, scrape_all_venues

REPO_ROOT = Path(__file__).parent
VENUES_CONFIG = REPO_ROOT / "venues.yaml"
EVENTS_OUTPUT = REPO_ROOT / "data" / "events.json"


def main() -> None:
    venues = load_venues(str(VENUES_CONFIG))
    events, failed = scrape_all_venues(venues)

    EVENTS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "failed_venues": failed,
        "events": [e.to_dict() for e in events],
    }
    EVENTS_OUTPUT.write_text(json.dumps(payload, indent=2))

    print(f"Scraped {len(events)} events from {len(venues)} venues.")
    if failed:
        print(f"Warning: failed to scrape: {', '.join(failed)}", file=sys.stderr)


if __name__ == "__main__":
    main()
