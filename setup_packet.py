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
            "helper_text": f.get("helper_text") or f.get("placeholder", ""),
        })
    return out


def generate_setup_packet(row: dict[str, str]) -> dict[str, Any]:
    text_fields = json.loads(row.get("personalization_fields_json") or row.get("text_fields_json") or "[]")
    image_fields = json.loads(row.get("image_upload_fields_json") or "[]")
    logo_fields = json.loads(row.get("logo_upload_fields_json") or "[]")
    preview_paths = json.loads(row.get("preview_artifacts_json") or "{}")

    buyer_schema = json.loads(row.get("buyer_personalization_schema_json") or "{}")
    packet = {
        "listing_id": row.get("id", ""),
        "listing_slug": row.get("listing_slug", ""),
        "listing_title": row.get("title", ""),
        "manual_setup_required": row.get("needs_manual_personalization_setup", "NO") == "YES",
        "text_fields": _field_packet(text_fields, "text"),
        "logo_fields": _field_packet(logo_fields, "logo"),
        "image_fields": _field_packet(image_fields, "image"),
        "recommended_preview_placeholder": row.get("placeholder_art_text", ""),
        "recommended_preview_artifact": preview_paths.get("primary_preview", row.get("asset_local_path", "")),
        "helper_text": buyer_schema.get("helper_text") or row.get("personalization_instructions", ""),
        "customer_can_edit_summary": row.get("customer_editable_summary", ""),
    }

    out_path = OUT / f"setup_packet_{row.get('listing_slug','listing')}.json"
    out_path.write_text(json.dumps(packet, indent=2), encoding="utf-8")
    return {"path": str(out_path), "packet": packet}
