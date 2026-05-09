from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Event:
    venue_name: str
    title: str
    date: Optional[datetime] = None
    date_raw: str = ""
    url: str = ""
    description: str = ""
    image_url: str = ""
    price: str = ""

    def sort_key(self) -> datetime:
        return self.date or datetime.max


@dataclass
class VenueConfig:
    name: str
    url: str
    strategy: str = "json-ld"
    # CSS selector strategy fields
    event_selector: str = ""
    title_selector: str = ""
    date_selector: str = ""
    url_selector: str = ""
    description_selector: str = ""
    price_selector: str = ""
    image_selector: str = ""
    # Optional base URL for resolving relative links
    base_url: str = ""
