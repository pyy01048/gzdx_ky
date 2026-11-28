"""Shared classification for automatic schema migrations and manual data scripts."""

from __future__ import annotations

import re
from pathlib import Path

MANUAL_DATA_RANGES = ((128, 203),)
MANUAL_DATA_VERSIONS = {
    "212_admission_details_anonymize",
    "213_school_official_url_guard",
}
_SCRIPT_RE = re.compile(r"^(\d{3})[a-z]?_")


def is_manual_data_script(path: Path | str) -> bool:
    match = _SCRIPT_RE.match(Path(path).name)
    if not match:
        return False
    number = int(match.group(1))
    return any(start <= number <= end for start, end in MANUAL_DATA_RANGES) or Path(path).stem in MANUAL_DATA_VERSIONS


def is_automatic_schema_script(path: Path | str) -> bool:
    return not is_manual_data_script(path)
