from __future__ import annotations

from typing import Any


def build_title(listing: dict[str, Any], template: dict[str, Any] | None = None) -> str:
    return listing.get("exact_title") or listing.get("title") or (template or {}).get("title_template") or "Crafted Occasion Personalized Product"


def build_seo_title(listing: dict[str, Any], template: dict[str, Any] | None = None) -> str:
    return listing.get("seo_title") or (template or {}).get("seo_title_template") or build_title(listing, template)


def build_description_html(listing: dict[str, Any], template: dict[str, Any] | None = None) -> str:
    return listing.get("exact_html_description") or listing.get("description_html") or (template or {}).get("description_template") or "<p>Personalized gift from Crafted Occasion.</p>"


def build_tags_csv(listing: dict[str, Any], collection: dict[str, Any]) -> str:
    tags = list(dict.fromkeys((listing.get("exact_tags") or []) + [collection["shopify_tag"]]))
    return ",".join(tags)
