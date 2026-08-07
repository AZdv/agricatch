"""Text munging shared by importers and field post-processing."""

from __future__ import annotations

import datetime
import html
import re
from urllib.parse import urljoin

TRANSLITERATIONS: dict[str, list[str]] = {
    "ae": ["Ä", "ä"],
    "oe": ["Ö", "ö"],
    "ue": ["Ü", "ü"],
    "ss": ["ß"],
}


def replace_all(text: str, mapping: dict[str, list[str] | str]) -> str:
    """Replace every value in ``mapping`` with its key. Values may be a list."""
    for replacement, targets in mapping.items():
        if not isinstance(targets, list):
            targets = [targets]
        for target in targets:
            text = text.replace(target, replacement)
    return text


def slugify(value: str, extra_clean: bool = True) -> str:
    value = replace_all(html.unescape(value).lower(), dict(TRANSLITERATIONS))
    if not extra_clean:
        return value
    value = re.sub(r"[^a-zA-Z0-9_\-\s]", "", value)
    value = re.sub(r"\s{2,}", " ", value)
    value = value.replace(" ", "-").replace("_", "-").strip(" -")
    return re.sub(r"-{2,}", "-", value)


def replace_parameters(value: str, when: datetime.date | None = None) -> str:
    """Expand the date placeholders an importer may embed in a URL."""
    when = when or datetime.date.today()
    today = datetime.date.today()
    parameters = {
        "%d": f"{when.day:02d}",
        "%m": f"{when.month:02d}",
        "%Y": f"{when.year:04d}",
        "%current_d%": f"{today.day:02d}",
        "%current_m%": f"{today.month:02d}",
        "%current_Y%": f"{today.year:04d}",
    }
    for placeholder, replacement in parameters.items():
        value = value.replace(placeholder, replacement)
    return value


def relative_url_to_absolute(url: str, base_url: str) -> str:
    return urljoin(base_url, url)


def collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
