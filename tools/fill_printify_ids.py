#!/usr/bin/env python3
"""Resolve Printify blueprint/provider IDs for catalog product profiles."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import requests
import yaml

BASE = "https://api.printify.com/v1"
DEFAULT_PROFILES_PATH = Path("catalog/product_profiles.yaml")
TOKEN_ENV = "PRINTIFY_TOKEN"

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
    "11oz",
    "15oz",
}

_SIZE_DIMENSION_RE = re.compile(
    r"\b\d{1,2}\s*(?:\"|in|inch|inches)?\s*x\s*\d{1,2}\s*(?:\"|in|inch|inches)?\b",
    flags=re.IGNORECASE,
)


class PrintifyRequestError(RuntimeError):
    pass


def _print(msg: str) -> None:
    print(msg, flush=True)


def _debug(enabled: bool, msg: str) -> None:
    if enabled:
        _print(f"[DEBUG] {msg}")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _request_json(token: str, path: str, *, debug: bool = False) -> Any:
    url = f"{BASE}{path}"
    _debug(debug, f"GET {path}")
    try:
        response = requests.get(url, headers=_headers(token), timeout=30)
    except requests.RequestException as exc:
        _print(f"[ERROR] GET {path} -> {exc}")
        raise PrintifyRequestError(str(exc)) from exc

    if response.status_code >= 400:
        snippet = response.text.strip().replace("\n", " ")[:200]
        status = response.status_code
        if status in {401, 403, 404, 429} or status >= 500:
            _print(f"[ERROR] GET {path} -> HTTP {status}: {snippet}")
        else:
            _print(f"[ERROR] GET {path} -> HTTP {status}")
        raise PrintifyRequestError(f"HTTP {status}")

    try:
        return response.json()
    except ValueError as exc:
        _print(f"[ERROR] GET {path} -> invalid JSON response")
        raise PrintifyRequestError("invalid JSON") from exc


def load_profiles(path: Path, *, debug: bool = False) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    _debug(debug, f"Loading profiles file: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        _print(f"[ERROR] Profiles file not found: {path}")
        raise
    except yaml.YAMLError as exc:
        _print(f"[ERROR] YAML parse error in {path}: {exc}")
        raise

    if not isinstance(raw, dict):
        _print(f"[ERROR] Unexpected YAML root type in {path}: {type(raw).__name__}")
        raise ValueError("Unexpected YAML root type")

    profiles = raw.get("product_profiles")
    if not isinstance(profiles, list):
        _print("[ERROR] Expected top-level key 'product_profiles' to be a list")
        raise ValueError("Invalid product_profiles structure")

    for idx, profile in enumerate(profiles):
        if not isinstance(profile, dict):
            _print(f"[ERROR] product_profiles[{idx}] is not a mapping")
            raise ValueError("Invalid profile entry")

    _debug(debug, f"Loaded {len(profiles)} product profiles")
    return raw, profiles


def discover_blueprints(token: str, *, debug: bool = False) -> list[dict[str, Any]]:
    data = _request_json(token, "/catalog/blueprints.json", debug=debug)
    if not isinstance(data, list):
        _print("[ERROR] Unexpected Printify blueprints response shape (expected list)")
        return []
    _debug(debug, f"Blueprints returned: {len(data)}")
    return [b for b in data if isinstance(b, dict)]


def providers_for_blueprint(token: str, blueprint_id: int, *, debug: bool = False) -> list[dict[str, Any]]:
    data = _request_json(token, f"/catalog/blueprints/{blueprint_id}/print_providers.json", debug=debug)
    if not isinstance(data, list):
        _print(f"[ERROR] Unexpected providers response for blueprint {blueprint_id} (expected list)")
        return []
    return [p for p in data if isinstance(p, dict)]


def provider_detail(token: str, blueprint_id: int, provider_id: int, *, debug: bool = False) -> dict[str, Any]:
    data = _request_json(
        token,
        f"/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}.json",
        debug=debug,
    )
    if not isinstance(data, dict):
        _print(f"[ERROR] Unexpected provider detail response for provider {provider_id}")
        return {}
    return data


def variants_for(token: str, blueprint_id: int, provider_id: int, *, debug: bool = False) -> list[dict[str, Any]]:
    data = _request_json(
        token,
        f"/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json",
        debug=debug,
    )
    if isinstance(data, dict):
        variants = data.get("variants", [])
    elif isinstance(data, list):
        variants = data
    else:
        _print(f"[ERROR] Unexpected variants response for provider {provider_id}")
        return []

    if not isinstance(variants, list):
        _print(f"[ERROR] Unexpected variants collection for provider {provider_id}")
        return []
    return [v for v in variants if isinstance(v, dict)]


def _normalize_option_entry(option: Any) -> str:
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
    if isinstance(option, (int, float, bool)):
        return str(option).strip()
    return ""


def _iter_options(options: Any) -> Iterable[Any]:
    if isinstance(options, list):
        return options
    if options is None:
        return ()
    return (options,)


def _looks_like_size(value: str) -> bool:
    if not value:
        return False
    lowered = value.strip().lower()
    if lowered in _SIZE_TOKENS:
        return True
    if re.fullmatch(r"(?:[smlx]{1,4}|\dxl)", lowered, flags=re.IGNORECASE):
        return True
    if _SIZE_DIMENSION_RE.search(lowered):
        return True
    return False


def extract_variant_attrs(variant: Any) -> tuple[str, str]:
    if not isinstance(variant, dict):
        return "", ""

    color = variant.get("color") if isinstance(variant.get("color"), str) else ""
    size = variant.get("size") if isinstance(variant.get("size"), str) else ""
    color = color.strip()
    size = size.strip()

    for raw_opt in _iter_options(variant.get("options")):
        normalized = _normalize_option_entry(raw_opt)
        if not normalized:
            continue
        if not size and _looks_like_size(normalized):
            size = normalized
            continue
        if not color:
            color = normalized

    title = variant.get("title")
    if (not color or not size) and isinstance(title, str):
        txt = title.strip()
        parts = [p.strip() for p in txt.split("/") if p.strip()] if "/" in txt else [txt]
        for part in parts:
            if not size and _looks_like_size(part):
                size = part
            elif not color:
                color = part

    return color or "", size or ""


def _norm(v: Any) -> str:
    return str(v).strip().lower()


def _variant_match_count(variants: list[dict[str, Any]], wanted_colors: set[str], wanted_sizes: set[str]) -> tuple[int, list[dict[str, Any]]]:
    matches: list[dict[str, Any]] = []
    for variant in variants:
        color, size = extract_variant_attrs(variant)
        c_ok = not wanted_colors or _norm(color) in wanted_colors
        s_ok = not wanted_sizes or _norm(size) in wanted_sizes
        if c_ok and s_ok:
            matches.append(variant)
    return len(matches), matches


def resolve_targets(profile: dict[str, Any], blueprints: list[dict[str, Any]], *, debug: bool = False) -> list[dict[str, Any]]:
    hints = profile.get("printify_blueprint_hints") if isinstance(profile.get("printify_blueprint_hints"), dict) else {}
    model_hint = str(hints.get("model", "")).strip().lower()
    label = str(profile.get("brand_model_label", "")).strip().lower()

    candidates: list[dict[str, Any]] = []
    for bp in blueprints:
        title = str(bp.get("title", "")).strip().lower()
        if model_hint and model_hint in title:
            candidates.append(bp)
            continue
        if label and any(chunk and chunk in title for chunk in label.split()[:2]):
            candidates.append(bp)

    if not candidates:
        # fallback: fuzzy by product family as a weak signal
        family = str(profile.get("product_family", "")).strip().lower()
        if family:
            for bp in blueprints:
                title = str(bp.get("title", "")).strip().lower()
                if family in title:
                    candidates.append(bp)

    _debug(debug, f"Profile {profile.get('id')} blueprint candidates: {[c.get('id') for c in candidates]}")
    return candidates


def _write_profiles(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def run(write_variants: bool, debug: bool) -> int:
    profiles_path = DEFAULT_PROFILES_PATH
    _print(f"[INFO] Starting Printify profile resolver for {profiles_path}")

    token = os.getenv(TOKEN_ENV, "").strip()
    if not token:
        _print(f"[ERROR] Missing {TOKEN_ENV}")
        _print(f"Updated 0 profile(s) in {profiles_path}")
        return 1

    try:
        doc, profiles = load_profiles(profiles_path, debug=debug)
    except Exception:
        _print(f"Updated 0 profile(s) in {profiles_path}")
        return 1

    _print(f"[INFO] Found {len(profiles)} profile(s)")

    try:
        blueprints = discover_blueprints(token, debug=debug)
    except PrintifyRequestError:
        _print(f"Updated 0 profile(s) in {profiles_path}")
        return 1

    changed = 0

    for profile in profiles:
        profile_id = profile.get("id", "<unknown>")
        try:
            candidates = resolve_targets(profile, blueprints, debug=debug)
            if not candidates:
                _print(f"[WARN] {profile_id}: no blueprint matches")
                continue

            wanted_colors = {_norm(c) for c in profile.get("launch_visible_colors", []) if isinstance(c, (str, int, float))}
            wanted_sizes = {_norm(s) for s in profile.get("launch_visible_sizes", []) if isinstance(s, (str, int, float))}

            best: tuple[int, dict[str, Any], dict[str, Any], list[dict[str, Any]]] | None = None
            for bp in candidates:
                bp_id = bp.get("id")
                if not isinstance(bp_id, int):
                    continue
                providers = providers_for_blueprint(token, bp_id, debug=debug)
                _debug(debug, f"Profile {profile_id} blueprint {bp_id} provider count: {len(providers)}")
                if not providers:
                    continue

                for provider in providers:
                    provider_id = provider.get("id")
                    if not isinstance(provider_id, int):
                        continue
                    _ = provider_detail(token, bp_id, provider_id, debug=debug)
                    variants = variants_for(token, bp_id, provider_id, debug=debug)
                    count, matched = _variant_match_count(variants, wanted_colors, wanted_sizes)
                    candidate = (count, bp, provider, matched)
                    if best is None or candidate[0] > best[0]:
                        best = candidate

            if best is None:
                _print(f"[WARN] {profile_id}: no provider matches")
                continue

            matched_count, best_bp, best_provider, matched_variants = best
            _debug(
                debug,
                f"Profile {profile_id} best provider {best_provider.get('id')} matched variant count: {matched_count}",
            )

            if matched_count == 0:
                _print(f"[WARN] {profile_id}: no matching variants")
                continue

            hints = profile.get("printify_blueprint_hints")
            if not isinstance(hints, dict):
                hints = {}
                profile["printify_blueprint_hints"] = hints

            old_bp = hints.get("blueprint_id")
            old_provider = hints.get("provider_id")
            hints["blueprint_id"] = int(best_bp["id"])
            hints["provider_id"] = int(best_provider["id"])

            if write_variants:
                meta = profile.get("full_catalog_metadata")
                if not isinstance(meta, dict):
                    meta = {}
                    profile["full_catalog_metadata"] = meta
                meta["printify_variant_ids"] = [v.get("id") for v in matched_variants if v.get("id") is not None]

            changed_now = old_bp != hints["blueprint_id"] or old_provider != hints["provider_id"]
            if changed_now:
                changed += 1
            _print(
                f"[OK] {profile_id}: blueprint_id={hints['blueprint_id']} provider_id={hints['provider_id']} "
                f"(matched_variants={matched_count})"
            )
        except PrintifyRequestError:
            _print(f"[ERROR] {profile_id}: request failed")
        except Exception as exc:
            _print(f"[ERROR] {profile_id}: unexpected error: {exc}")

    try:
        _write_profiles(profiles_path, doc)
    except Exception as exc:
        _print(f"[ERROR] Failed to write {profiles_path}: {exc}")
        _print(f"Updated {changed} profile(s) in {profiles_path}")
        return 1

    _print(f"Updated {changed} profile(s) in {profiles_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fill Printify blueprint/provider IDs in catalog profiles")
    parser.add_argument("--write-variants", action="store_true", help="Also write matched Printify variant IDs")
    parser.add_argument("--debug", action="store_true", help="Print verbose diagnostics")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    code = run(write_variants=args.write_variants, debug=args.debug)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
