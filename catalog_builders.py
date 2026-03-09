from __future__ import annotations

from typing import Any


def _first_text_field(listing: dict[str, Any], template: dict[str, Any]) -> str:
    fields = listing.get("personalization_fields") or template.get("personalization_fields") or []
    for f in fields:
        if isinstance(f, dict) and f.get("field_type") in {"text", "date", "choice"}:
            return str(f.get("field_label") or f.get("field_key") or "Name")
    return "Custom Text"


def build_title(listing: dict[str, Any], template: dict[str, Any] | None = None) -> str:
    template = template or {}
    if listing.get("exact_title"):
        return str(listing["exact_title"])
    collection = (listing.get("collection_slug") or template.get("collection_slug") or "occasion").replace("-", " ").title()
    profile = (listing.get("product_profile_id") or template.get("product_profile_id") or "product").split("_")[0].title()
    hook = _first_text_field(listing, template)
    base = str(listing.get("title") or template.get("title_template") or f"{collection} Personalized {profile}")
    if "Personalized" not in base:
        base = f"{base} Personalized"
    return f"{base} | {hook} {profile}"[:140]


def build_seo_title(listing: dict[str, Any], template: dict[str, Any] | None = None) -> str:
    template = template or {}
    if listing.get("seo_title"):
        return str(listing["seo_title"])
    occasion = (listing.get("collection_slug") or template.get("collection_slug") or "gift").replace("-", " ")
    product = (listing.get("product_profile_id") or template.get("product_profile_id") or "product").split("_")[0]
    hook = _first_text_field(listing, template).lower()
    return f"{occasion.title()} {product.title()} Personalized with {hook} | Crafted Occasion"[:140]


def build_description_html(listing: dict[str, Any], template: dict[str, Any] | None = None) -> str:
    template = template or {}
    if listing.get("exact_html_description"):
        return str(listing["exact_html_description"])

    product = (listing.get("product_profile_id") or template.get("product_profile_id") or "product").split("_")[0].title()
    collection = (listing.get("collection_slug") or template.get("collection_slug") or "special occasions").replace("-", " ")
    personalization_fields = listing.get("personalization_fields") or template.get("personalization_fields") or []
    details = ", ".join([(f.get("field_label") or f.get("field_key") or "Custom field") for f in personalization_fields if isinstance(f, dict)]) or "custom name or date"
    bullets = listing.get("description_bullets") or template.get("description_bullets") or []

    html = [
        f"<p>Designed for {collection}, this personalized {product.lower()} blends elevated styling with gift-ready quality from Crafted Occasion.</p>",
        f"<p><strong>Personalization:</strong> Customize with {details}. Upload-ready fields can be configured in Printify Personalization Hub after publish.</p>",
        f"<p><strong>Perfect for:</strong> reunions, milestone photos, wedding weekends, bridal events, and meaningful keepsake gifting.</p>",
    ]
    if bullets:
        html.append("<ul>" + "".join([f"<li>{b}</li>" for b in bullets]) + "</ul>")
    return "".join(html)


def build_tags_csv(listing: dict[str, Any], collection: dict[str, Any], template: dict[str, Any] | None = None, profile: dict[str, Any] | None = None) -> str:
    template = template or {}
    profile = profile or {}
    seeds: list[str] = []
    seeds.extend(listing.get("exact_tags") or [])
    seeds.extend(template.get("tags") or [])
    seeds.extend(template.get("seo_keywords") or [])
    seeds.extend(template.get("merchandising_keywords") or [])
    seeds.extend([collection.get("shopify_tag", ""), collection.get("slug", "")])
    seeds.extend([profile.get("product_family", ""), "gift", "personalized"])
    for field in (listing.get("personalization_fields") or template.get("personalization_fields") or []):
        if isinstance(field, dict):
            seeds.append(str(field.get("field_key") or ""))
    normalized = [s.strip().lower().replace(" ", "-") for s in seeds if isinstance(s, str) and s.strip()]
    return ",".join(list(dict.fromkeys(normalized)))
