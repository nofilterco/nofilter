from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml

CATALOG_DIR = Path("catalog")


def _load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_catalog() -> dict[str, Any]:
    return {
        "collections": _load_yaml(CATALOG_DIR / "collections.yaml").get("collections", []),
        "product_profiles": _load_yaml(CATALOG_DIR / "product_profiles.yaml").get("product_profiles", []),
        "listing_templates": _load_yaml(CATALOG_DIR / "listing_templates.yaml").get("listing_templates", []),
        "launch_plan": _load_yaml(CATALOG_DIR / "launch_plan.yaml").get("launch_listings", []),
        "publish_defaults": _load_yaml(CATALOG_DIR / "publish_defaults.yaml").get("publish_defaults", {}),
    }


def catalog_indexes(catalog: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        "collections": {c["slug"]: c for c in catalog["collections"]},
        "profiles": {p["id"]: p for p in catalog["product_profiles"]},
        "templates": {t["slug"]: t for t in catalog["listing_templates"]},
    }
