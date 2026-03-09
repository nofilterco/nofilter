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


def _request_json(token: str, path: str, *, debug_http: bool = False) -> Any:
    url = f"{BASE}{path}"
    _debug(debug_http, f"GET {path}")
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


def discover_blueprints(token: str, *, debug: bool = False, debug_http: bool = False) -> list[dict[str, Any]]:
    data = _request_json(token, "/catalog/blueprints.json", debug_http=debug_http)
    if not isinstance(data, list):
        _print("[ERROR] Unexpected Printify blueprints response shape (expected list)")
        return []
    _debug(debug, f"Blueprints returned: {len(data)}")
    return [b for b in data if isinstance(b, dict)]


def providers_for_blueprint(token: str, blueprint_id: int, *, debug_http: bool = False) -> list[dict[str, Any]]:
    data = _request_json(token, f"/catalog/blueprints/{blueprint_id}/print_providers.json", debug_http=debug_http)
    if not isinstance(data, list):
        _print(f"[ERROR] Unexpected providers response for blueprint {blueprint_id} (expected list)")
        return []
    return [p for p in data if isinstance(p, dict)]


def variants_for(token: str, blueprint_id: int, provider_id: int, *, debug_http: bool = False) -> list[dict[str, Any]]:
    data = _request_json(
        token,
        f"/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json",
        debug_http=debug_http,
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


def _blueprint_preference_score(profile_id: str, blueprint: dict[str, Any]) -> int:
    title = _norm(blueprint.get("title"))
    brand = _norm(blueprint.get("brand"))
    model = _norm(blueprint.get("model"))
    text = " ".join([title, brand, model])

    if profile_id == "youth_tee_g5000b":
        score = 0
        if "g5000b" in text:
            score += 40
        if "youth" in text:
            score += 24
        if "g5000" in text:
            score += 10
        if "adult" in text:
            score -= 16
        return score

    if profile_id == "adult_tee_g5000":
        score = 0
        if "g5000" in text and "g5000b" not in text:
            score += 38
        if "adult" in text:
            score += 10
        if "youth" in text:
            score -= 20
        return score

    if profile_id == "crewneck_g18000":
        score = 0
        if "g18000" in text:
            score += 40
        if "crewneck" in text or "sweatshirt" in text:
            score += 18
        if "hoodie" in text:
            score -= 12
        return score

    if profile_id == "hoodie_g18500":
        score = 0
        if "g18500" in text:
            score += 40
        if "hoodie" in text:
            score += 18
        if "crewneck" in text or "sweatshirt" in text:
            score -= 10
        return score

    if profile_id == "mug_orca_color":
        score = 0
        if "orca" in text:
            score += 35
        if "mug" in text:
            score += 18
        if any(word in text for word in ("color", "colorful", "accent")):
            score += 14
        return score

    if profile_id == "tote_liberty_canvas":
        score = 0
        if "liberty" in text:
            score += 35
        if "bags" in text:
            score += 8
        if "canvas" in text:
            score += 16
        if "tote" in text:
            score += 16
        return score

    return 0


def _is_exact_model_match(profile_id: str, blueprint: dict[str, Any]) -> bool:
    text = " ".join([
        _norm(blueprint.get("title")),
        _norm(blueprint.get("brand")),
        _norm(blueprint.get("model")),
    ])
    exact_markers = {
        "youth_tee_g5000b": "g5000b",
        "adult_tee_g5000": "g5000",
        "crewneck_g18000": "g18000",
        "hoodie_g18500": "g18500",
        "mug_orca_color": "orca",
        "tote_liberty_canvas": "liberty",
    }
    marker = exact_markers.get(profile_id)
    if not marker:
        return False
    if profile_id == "adult_tee_g5000":
        return marker in text and "g5000b" not in text
    return marker in text


def resolve_targets(
    profile: dict[str, Any],
    blueprints: list[dict[str, Any]],
    *,
    debug: bool = False,
    max_blueprints_per_profile: int = 5,
) -> tuple[list[dict[str, Any]], int]:
    hints = profile.get("printify_blueprint_hints") if isinstance(profile.get("printify_blueprint_hints"), dict) else {}
    model_hint = str(hints.get("model", "")).strip().lower()
    label = str(profile.get("brand_model_label", "")).strip().lower()
    profile_id = str(profile.get("id", ""))

    scored: list[tuple[int, dict[str, Any]]] = []
    total_candidates = 0
    for bp in blueprints:
        title = str(bp.get("title", "")).strip().lower()
        strong_hit = False
        if model_hint and model_hint in title:
            strong_hit = True
        if label and any(chunk and chunk in title for chunk in label.split()[:2]):
            strong_hit = True

        if strong_hit:
            total_candidates += 1
            score = _blueprint_preference_score(profile_id, bp)
            scored.append((score, bp))

    if not scored:
        family = str(profile.get("product_family", "")).strip().lower()
        if family:
            for bp in blueprints:
                title = str(bp.get("title", "")).strip().lower()
                if family in title:
                    total_candidates += 1
                    score = _blueprint_preference_score(profile_id, bp)
                    scored.append((score, bp))

    scored.sort(key=lambda x: x[0], reverse=True)
    shortlisted = [bp for _, bp in scored[:max_blueprints_per_profile]]
    _debug(debug, f"Profile {profile.get('id')} total blueprint candidates: {total_candidates}")
    _debug(debug, f"Profile {profile.get('id')} shortlisted blueprint IDs: {[c.get('id') for c in shortlisted]}")
    return shortlisted, total_candidates


def _write_profiles(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def run(write_variants: bool, debug: bool, debug_http: bool, max_blueprints_per_profile: int, max_providers_per_blueprint: int) -> int:
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
        blueprints = discover_blueprints(token, debug=debug, debug_http=debug_http)
    except PrintifyRequestError:
        _print(f"Updated 0 profile(s) in {profiles_path}")
        return 1

    changed = 0
    providers_cache: dict[int, list[dict[str, Any]]] = {}
    variants_cache: dict[tuple[int, int], list[dict[str, Any]]] = {}

    for profile in profiles:
        profile_id = profile.get("id", "<unknown>")
        try:
            candidates, _total_candidates = resolve_targets(
                profile,
                blueprints,
                debug=debug,
                max_blueprints_per_profile=max_blueprints_per_profile,
            )
            if not candidates:
                _print(f"[WARN] {profile_id}: no blueprint matches")
                continue

            wanted_colors = {_norm(c) for c in profile.get("launch_visible_colors", []) if isinstance(c, (str, int, float))}
            wanted_sizes = {_norm(s) for s in profile.get("launch_visible_sizes", []) if isinstance(s, (str, int, float))}

            best: tuple[int, int, dict[str, Any], dict[str, Any], list[dict[str, Any]]] | None = None
            wanted_combo_count = max(1, len(wanted_colors) * len(wanted_sizes))
            for bp in candidates:
                bp_id = bp.get("id")
                if not isinstance(bp_id, int):
                    continue
                preference = _blueprint_preference_score(str(profile_id), bp)
                if bp_id in providers_cache:
                    providers = providers_cache[bp_id]
                else:
                    providers = providers_for_blueprint(token, bp_id, debug_http=debug_http)
                    providers_cache[bp_id] = providers
                if max_providers_per_blueprint > 0:
                    providers = providers[:max_providers_per_blueprint]
                _debug(debug, f"Profile {profile_id} blueprint {bp_id} provider count evaluated: {len(providers)}")
                if not providers:
                    continue

                for provider in providers:
                    provider_id = provider.get("id")
                    if not isinstance(provider_id, int):
                        continue
                    key = (bp_id, provider_id)
                    try:
                        if key in variants_cache:
                            variants = variants_cache[key]
                        else:
                            variants = variants_for(token, bp_id, provider_id, debug_http=debug_http)
                            variants_cache[key] = variants
                    except PrintifyRequestError:
                        _print(
                            f"[WARN] {profile_id}: variants lookup failed for blueprint={bp_id} provider={provider_id}; continuing"
                        )
                        continue
                    count, matched = _variant_match_count(variants, wanted_colors, wanted_sizes)
                    candidate = (count, preference, bp, provider, matched)
                    if best is None or (candidate[0], candidate[1]) > (best[0], best[1]):
                        best = candidate

                if best is not None:
                    best_count, _, best_bp, _best_provider, _best_matched = best
                    if _is_exact_model_match(str(profile_id), best_bp) and best_count >= int(0.7 * wanted_combo_count):
                        _debug(
                            debug,
                            f"Profile {profile_id} early exit on blueprint {best_bp.get('id')} with strong match coverage ({best_count}/{wanted_combo_count})",
                        )
                        break

            if best is None:
                _print(f"[WARN] {profile_id}: no provider matches")
                continue

            matched_count, _, best_bp, best_provider, matched_variants = best
            _debug(
                debug,
                f"Profile {profile_id} best provider selected: {best_provider.get('id')} (blueprint={best_bp.get('id')})",
            )
            _debug(debug, f"Profile {profile_id} matched variant count: {matched_count}")

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
            _debug(
                debug,
                f"Profile {profile_id} final selection: blueprint_id={hints['blueprint_id']} provider_id={hints['provider_id']}",
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
    parser.add_argument("--debug-http", action="store_true", help="Print each HTTP request")
    parser.add_argument("--max-blueprints-per-profile", type=int, default=5, help="Max shortlisted blueprints per profile")
    parser.add_argument("--max-providers-per-blueprint", type=int, default=0, help="Optional cap for providers checked per blueprint (0=all)")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    code = run(
        write_variants=args.write_variants,
        debug=args.debug,
        debug_http=args.debug_http,
        max_blueprints_per_profile=max(1, args.max_blueprints_per_profile),
        max_providers_per_blueprint=max(0, args.max_providers_per_blueprint),
    )
    raise SystemExit(code)


if __name__ == "__main__":
    main()
