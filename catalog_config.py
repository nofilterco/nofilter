from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CATALOG_DIR = Path("catalog")


def _load_yaml(path: Path) -> Any:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _resolve_launch_listings(root: dict[str, Any]) -> list[dict[str, Any]]:
    """Return launch listings from explicit plan (current source of truth).

    `launch_batches.yaml` is loaded for batch orchestration metadata, but launch rows
    continue to come from `launch_plan.yaml` for backward compatibility.
    """
    return root.get("launch_plan", [])


def load_catalog() -> dict[str, Any]:
    catalog = {
        "collections": _load_yaml(CATALOG_DIR / "collections.yaml").get("collections", []),
        "product_profiles": _load_yaml(CATALOG_DIR / "product_profiles.yaml").get("product_profiles", []),
        "listing_templates": _load_yaml(CATALOG_DIR / "listing_templates.yaml").get("listing_templates", []),
        "launch_plan": _load_yaml(CATALOG_DIR / "launch_plan.yaml").get("launch_listings", []),
        "publish_defaults": _load_yaml(CATALOG_DIR / "publish_defaults.yaml").get("publish_defaults", {}),
        "niches": _load_yaml(CATALOG_DIR / "niches.yaml").get("niches", []),
        "template_families": _load_yaml(CATALOG_DIR / "template_families.yaml").get("template_families", []),
        "personalization_fields": _load_yaml(CATALOG_DIR / "personalization_fields.yaml").get("personalization_fields", []),
        "launch_batches": _load_yaml(CATALOG_DIR / "launch_batches.yaml").get("launch_batches", []),
        "qa_policies": _load_yaml(CATALOG_DIR / "qa_scoring.yaml").get("qa_policies", []),
        "publish_diagnostics": _load_yaml(CATALOG_DIR / "publish_diagnostics.yaml").get("diagnostic_dimensions", []),
    }
    catalog["launch_listings"] = _resolve_launch_listings(catalog)
    return catalog


def catalog_indexes(catalog: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        "collections": {c["slug"]: c for c in catalog["collections"]},
        "profiles": {p["id"]: p for p in catalog["product_profiles"]},
        "templates": {t["slug"]: t for t in catalog["listing_templates"]},
        "niches": {n["id"]: n for n in catalog.get("niches", [])},
        "template_families": {t["id"]: t for t in catalog.get("template_families", [])},
        "launch_batches": {b["batch_id"]: b for b in catalog.get("launch_batches", [])},
        "qa_policies": {p["id"]: p for p in catalog.get("qa_policies", [])},
    }
