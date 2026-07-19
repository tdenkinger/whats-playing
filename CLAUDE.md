# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # adds pytest

# Run the app
streamlit run app.py

# Run tests
pytest tests/

# Run a single test file
pytest tests/test_venue_scraper.py -v
```

## Architecture

**What's Playing** is a Streamlit web app that scrapes music venue event listings and displays them aggregated and sorted by date.

### Data flow

1. `venues.yaml` — defines which venues to scrape and how (strategy + CSS selectors)
2. `scraper/venue_scraper.py` — fetches pages and extracts events using one of two strategies
3. `scraper/models.py` — two dataclasses: `VenueConfig` (scraping config) and `Event` (scraped result)
4. `app.py` — Streamlit UI: loads venues, triggers scraping, filters, and renders events grouped by date then venue

### Scraping strategies

`VenueConfig.strategy` controls which path `scrape_venue()` takes:

- **`json-ld`** (default): parses `<script type="application/ld+json">` blocks, filtering for `@type` of `Event`, `MusicEvent`, or `Concert`. Falls back to CSS selectors if the page has `event_selector` defined but json-ld yields nothing.
- **`css`**: uses `event_selector` to find event blocks, then child selectors (`title_selector`, `date_selector`, `url_selector`, `description_selector`, `price_selector`, `image_selector`) to extract fields from each block.

Dates are parsed liberally via `python-dateutil` with `fuzzy=True`. Relative URLs are resolved using `base_url` (or falls back to `url`).

### Adding a new venue

Add an entry to `venues.yaml`. For sites with JSON-LD structured data, only `name` and `url` are needed. For sites without, use `strategy: css` and inspect the page HTML to find appropriate CSS selectors. The `venues.yaml` file contains detailed comments and examples.
