import os
import shutil
from pathlib import Path

REPO_VENUES_CONFIG = Path(__file__).parent / "venues.yaml"

_data_dir = os.environ.get("DATA_DIR")
if _data_dir:
    VENUES_CONFIG = Path(_data_dir) / "venues.yaml"
    if not VENUES_CONFIG.exists() and REPO_VENUES_CONFIG.exists():
        VENUES_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_VENUES_CONFIG, VENUES_CONFIG)
else:
    VENUES_CONFIG = REPO_VENUES_CONFIG
