from __future__ import annotations

from typing import Any


ROLE_PHRASES = {
    "bridesmaid": "Bridesmaid",
    "maid of honor": "Maid of Honor",
    "bride crew": "Bride Crew",
    "groom crew": "Groom Crew",
    "bach weekend": "Bachelorette Weekend",
    "family reunion": "Family Reunion",
}

INTERNAL_FIELD_KEYS = {
    "person_name", "role", "event_year", "destination", "wedding_city", "last_name", "wedding_date",
    "family_name", "reunion_year", "reunion_city", "child_name", "established_year", "couple_names",
}


def _product_phrase(profile_id: str) -> str:
    tokenized = (profile_id or "product").lower()
    family = "product"
    for candidate in ("tee", "hoodie", "crewneck", "mug", "tote"):
        if candidate in tokenized:
            family = candidate
            break
    return {
        "tee": "T-Shirt",
        "hoodie": "Hoodie",
        "crewneck": "Crewneck Sweatshirt",
        "mug": "Mug",
        "tote": "Tote Bag",
    }.get(family, family.title())


def _role_phrase(listing: dict[str, Any], template: dict[str, Any]) -> str:
    raw_title = (listing.get("exact_title") or listing.get("title") or template.get("title_template") or "").lower()
    coll = (listing.get("collection_slug") or template.get("collection_slug") or "").replace("-", " ").lower()
    tags = " ".join([str(t).lower() for t in (listing.get("exact_tags") or [])])
    haystack = f"{raw_title} {coll} {tags}"
    for key, phrase in ROLE_PHRASES.items():
        if key in haystack:
            return phrase
    return ""


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
    product = _product_phrase(listing.get("product_profile_id") or template.get("product_profile_id") or "")
    role = _role_phrase(listing, template)
    hook = _first_text_field(listing, template)
    parts = [p for p in [collection, role, f"Personalized {product}"] if p]
    return " - ".join(parts + [f"Custom {hook}"])[:140]


def build_seo_title(listing: dict[str, Any], template: dict[str, Any] | None = None) -> str:
    template = template or {}
    if listing.get("seo_title"):
        return str(listing["seo_title"])
    occasion = (listing.get("collection_slug") or template.get("collection_slug") or "gift").replace("-", " ").title()
    product = _product_phrase(listing.get("product_profile_id") or template.get("product_profile_id") or "")
    role = _role_phrase(listing, template)
    hook = _first_text_field(listing, template)
    intent = "Custom Gift"
    if "reunion" in occasion.lower():
        intent = "Matching Family Gift"
    if role in {"Bride Crew", "Groom Crew", "Bachelorette Weekend"}:
        intent = "Wedding Weekend Gift"
    core = " ".join([p for p in [occasion, role, product] if p])
    return f"{core} - Personalized with {hook} | {intent} | Crafted Occasion"[:140]


def build_description_html(listing: dict[str, Any], template: dict[str, Any] | None = None) -> str:
    template = template or {}
    if listing.get("exact_html_description"):
        return str(listing["exact_html_description"])

    product = _product_phrase(listing.get("product_profile_id") or template.get("product_profile_id") or "")
    collection = (listing.get("collection_slug") or template.get("collection_slug") or "special occasions").replace("-", " ")
    personalization_fields = listing.get("personalization_fields") or template.get("personalization_fields") or []
    details = ", ".join([(f.get("field_label") or f.get("field_key") or "Custom field") for f in personalization_fields if isinstance(f, dict)]) or "custom name or date"
    bullets = listing.get("description_bullets") or template.get("description_bullets") or []

    role = _role_phrase(listing, template)
    role_text = f" for {role.lower()}" if role else ""
    html = [f"<p>This personalized {product.lower()}{role_text} is designed for {collection} celebrations and meaningful gifting. Customize with {details} for a polished, event-ready keepsake.</p>"]
    if bullets:
        html.append("<ul>" + "".join([f"<li>{b}</li>" for b in bullets[:3]]) + "</ul>")
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
    seeds.extend(collection.get("default_keywords") or [])
    role = _role_phrase(listing, template)
    if role:
        seeds.append(role)
    if (template.get("supports_text_edit") is True) or (listing.get("personalization_fields") or template.get("personalization_fields")):
        seeds.append("customizable")
    for field in (listing.get("personalization_fields") or template.get("personalization_fields") or []):
        if isinstance(field, dict):
            key = str(field.get("field_key") or "")
            if key and key not in INTERNAL_FIELD_KEYS:
                seeds.append(key)
    normalized = [s.strip().lower().replace(" ", "-") for s in seeds if isinstance(s, str) and s.strip() and s.strip().lower() not in INTERNAL_FIELD_KEYS]
    return ",".join(list(dict.fromkeys(normalized)))
