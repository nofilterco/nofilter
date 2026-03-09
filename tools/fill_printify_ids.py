#!/usr/bin/env python3
"""Utilities for filling Printify IDs.

This module includes resilient variant attribute extraction logic used by the
CLI workflow in this script.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

_SIZE_TOKENS = {
    "xxs",
    "xs",
    "s",
    "m",
    "l",
    "xl",
    "xxl",
    "xxxl",
    "2xl",
    "3xl",
    "4xl",
    "5xl",
    "one size",
    "os",
}

_SIZE_DIMENSION_RE = re.compile(
    r"\b\d{1,2}\s*(?:\"|in|inch|inches)?\s*x\s*\d{1,2}\s*(?:\"|in|inch|inches)?\b",
    flags=re.IGNORECASE,
)


def _normalize_option_entry(option: Any) -> str:
    """Normalize a variant options entry into a safe string.

    Supports options entries as dicts ({"name": ..., "value": ...}), plain
    strings, and mixed malformed values. Unknown values normalize to "".
    """

    if option is None:
        return ""

    if isinstance(option, str):
        return option.strip()

    if isinstance(option, dict):
        value = option.get("value")
        if isinstance(value, str) and value.strip():
            return value.strip()

        name = option.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()

        return ""

    # Fall back for unexpected primitive types.
    if isinstance(option, (int, float, bool)):
        return str(option).strip()

    return ""


def _looks_like_size(value: str) -> bool:
    if not value:
        return False

    lowered = value.strip().lower()
    if lowered in _SIZE_TOKENS:
        return True

    # e.g. S, M, L, XL, 2XL
    if re.fullmatch(r"(?:[smlx]{1,4}|\dxl)", lowered, flags=re.IGNORECASE):
        return True

    # e.g. 15x16, 15 x 16, 15" x 16"
    if _SIZE_DIMENSION_RE.search(lowered):
        return True

    return False


def _iter_options(options: Any) -> Iterable[Any]:
    if isinstance(options, list):
        return options
    if options is None:
        return ()
    return (options,)


def extract_variant_attrs(variant: Any) -> tuple[str, str]:
    """Extract (color, size) from a Printify variant payload safely.

    Inference order:
    1) explicit variant["size"] / variant["color"]
    2) variant["options"] entries
    3) title fallback like "Black / S"

    Returns ("", "") when no usable attributes are found.
    """

    if not isinstance(variant, dict):
        return "", ""

    color = ""
    size = ""

    explicit_color = variant.get("color")
    explicit_size = variant.get("size")
    if isinstance(explicit_color, str):
        color = explicit_color.strip()
    if isinstance(explicit_size, str):
        size = explicit_size.strip()

    for raw_opt in _iter_options(variant.get("options")):
        normalized = _normalize_option_entry(raw_opt)
        if not normalized:
            continue

        if not size and _looks_like_size(normalized):
            size = normalized
            continue

        if not color:
            color = normalized

    if (not color or not size) and isinstance(variant.get("title"), str):
        title = variant["title"].strip()
        if "/" in title:
            parts = [p.strip() for p in title.split("/") if p and p.strip()]
            for part in parts:
                if not size and _looks_like_size(part):
                    size = part
                elif not color:
                    color = part
        else:
            if not size and _looks_like_size(title):
                size = title
            elif not color:
                color = title

    return color or "", size or ""
