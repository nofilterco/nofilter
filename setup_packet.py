from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUT = Path("out/setup_packets")
OUT.mkdir(parents=True, exist_ok=True)


def _field_packet(fields: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    out = []
    for f in fields:
        out.append({
            "type": kind,
            "key": f.get("field_key", ""),
            "label": f.get("field_label") or f.get("label") or f.get("field_key", ""),
            "required": bool(f.get("required", False)),
            "max_length": f.get("max_length", ""),
            "upload_type": f.get("upload_type", kind if kind in {"image", "logo"} else ""),
            "helper_text": f.get("helper_text") or f.get("placeholder", ""),
        })
    return out


def _storefront_copy_snippets(has_text: bool, has_image: bool, has_logo: bool) -> list[str]:
    snippets = []
    if has_text:
        snippets.append("Customize with your name")
    if has_image:
        snippets.append("Upload a family photo")
    if has_logo:
        snippets.append("Add your monogram logo")
    return snippets


def generate_setup_packet(row: dict[str, str]) -> dict[str, Any]:
    text_fields = json.loads(row.get("personalization_fields_json") or row.get("text_fields_json") or "[]")
    image_fields = json.loads(row.get("image_upload_fields_json") or "[]")
    logo_fields = json.loads(row.get("logo_upload_fields_json") or "[]")
    preview_paths = json.loads(row.get("preview_artifacts_json") or "{}")

    buyer_schema = json.loads(row.get("buyer_personalization_schema_json") or "{}")
    text_packet = _field_packet(text_fields, "text")
    logo_packet = _field_packet(logo_fields, "logo")
    image_packet = _field_packet(image_fields, "image")

    has_text, has_image, has_logo = bool(text_packet), bool(image_packet), bool(logo_packet)
    snippet_list = _storefront_copy_snippets(has_text, has_image, has_logo)

    packet = {
        "listing_id": row.get("id", ""),
        "listing_slug": row.get("listing_slug", ""),
        "listing_title": row.get("title", ""),
        "manual_setup_required": row.get("needs_manual_personalization_setup", "NO") == "YES",
        "text_fields": text_packet,
        "logo_fields": logo_packet,
        "image_fields": image_packet,
        "recommended_preview_placeholder": row.get("placeholder_art_text", ""),
        "recommended_preview_artifact": preview_paths.get("primary_preview", row.get("asset_local_path", "")),
        "helper_text": buyer_schema.get("helper_text") or row.get("personalization_instructions", ""),
        "customer_can_edit_summary": row.get("customer_editable_summary", ""),
        "manual_setup_guide": {
            "hub": "Printify Personalization Hub",
            "field_definitions": {
                "text": text_packet,
                "image": image_packet,
                "logo": logo_packet,
            },
            "required_vs_optional": [{"label": f["label"], "required": f["required"]} for f in [*text_packet, *image_packet, *logo_packet]],
            "text_limits": [{"label": f["label"], "max_length": f.get("max_length", "")} for f in text_packet],
            "upload_field_types": [{"label": f["label"], "upload_type": f.get("upload_type", f.get("type", ""))} for f in [*image_packet, *logo_packet]],
            "buyer_helper_text_suggestions": [f.get("helper_text", "") for f in [*text_packet, *image_packet, *logo_packet] if f.get("helper_text")],
            "storefront_copy_suggestions": {
                "headline": row.get("storefront_personalization_headline", "Make it yours"),
                "subtext": row.get("storefront_personalization_subtext", "Add your name, date, photo, or logo before checkout"),
                "badges": [b.strip() for b in (row.get("storefront_badges", "")).split(",") if b.strip()],
                "product_page_snippets": snippet_list,
            },
        },
    }

    out_path = OUT / f"setup_packet_{row.get('listing_slug','listing')}.json"
    out_path.write_text(json.dumps(packet, indent=2), encoding="utf-8")
    return {"path": str(out_path), "packet": packet}
