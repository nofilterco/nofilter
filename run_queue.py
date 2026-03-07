import argparse
import csv
import os
import random
import hashlib
import json
import sys
from datetime import datetime, timezone
from typing import List, Dict, Tuple, Optional

from dotenv import load_dotenv

from phrase_engine import pick_phrase
from title_builder import build_title
from description_builder import build_description
from design_factory import build_design
from mockup_factory import make_simple_hat_mockup
from quality_gate import pass_fail
from r2_upload import upload_file
from nostalgia_blueprint import (
    pick_brief,
    detect_risk,
    STYLE_CHOICES,
    brief_from_row,
    evaluate_embroidery_concept,
)
from drops import get_drop_names, get_drop_limited, build_drop_tags, get_drop_title
from drop_limits import can_publish, increment

from publish_hat import (
    upload_image_by_url,
    create_hat_product,
    publish_product,
    get_shop_id,
    find_hat_blueprint,
    pick_print_provider,
    get_variants,
    choose_hat_variant_ids,
)

QUEUE_PATH = "queue.csv"
AUTO_SEED_IF_EMPTY = 5  # auto-add N NEW rows if nothing is publishable


# ----------------------------
# Helpers
# ----------------------------
def slugify(s: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in (s or ""))[:80].strip("-")


def _sha1(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()


def _env_true(name: str, default: str = "0") -> bool:
    v = (os.getenv(name, default) or "").strip().lower()
    return v in ("1", "true", "yes", "y", "on")


def _windows_safe_text(msg: str) -> str:
    """Avoid UnicodeEncodeError on legacy Windows consoles."""
    if os.name != "nt":
        return msg
    return msg.encode("ascii", errors="replace").decode("ascii")


def log(msg: str) -> None:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    print(_windows_safe_text(msg))


def load_queue() -> List[Dict[str, str]]:
    if not os.path.exists(QUEUE_PATH):
        raise FileNotFoundError(f"Missing {QUEUE_PATH}. Create it in the project folder.")
    with open(QUEUE_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_queue(rows: List[Dict[str, str]]) -> None:
    if not rows:
        return

    fieldnames = list(rows[0].keys())

    # Ensure these columns exist even if older queue.csv is missing them
    for extra in (
        "local_path",
        "generated_at",
        "prompt_debug",
        "prompt_hash",
        "resolved_style",
        "quality_status",
        "quality_reason",
        "quality_json",
        "drop_seq",
        "approved_at",
        "printify_product_id",
        "published_at",
        "r2_url",
        "mockup_r2_url",
        "printify_image_id",
        "placement",
        "product_type",
        "drop",
        "motif",
        "risk_flag",
        "policy_status",
        "risk_reason",
        "drop_title",
        "vibe",
        "tone",
        "embroidery_focus",
        "embroidery_style",
        "palette_hint",
        "micro_niche",
        "object_state",
        "era_situation",
        "texture_cue",
        "variation_modifier",
        "motif_family",
        "motif_frame",
        "motif_keywords",
        "center_weight",
        "silhouette_strength",
        "product_rules",
    ):
        if extra not in fieldnames:
            fieldnames.append(extra)

    with open(QUEUE_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def pick_next_row_index(rows: List[Dict[str, str]]) -> Optional[int]:
    """
    Policy gate:
      - status must be APPROVED or NEW
      - NEVER publish GENERATED (awaiting human review)
      - if risk_flag == REVIEW, policy_status must be APPROVED
      - skip HOLD_QUALITY / HOLD_ERROR / SOLD_OUT
    """
    for desired_status in ("APPROVED", "NEW"):
        for i, r in enumerate(rows):
            status = (r.get("status", "") or "").strip().upper()
            if status != desired_status:
                continue

            if status == "GENERATED":
                continue

            risk = (r.get("risk_flag", "SAFE") or "SAFE").strip().upper()
            policy = (r.get("policy_status", "") or "").strip().upper()
            if risk == "REVIEW" and policy != "APPROVED":
                continue

            return i
    return None


def _analytics_tags(r: dict) -> list[str]:
    """Extra tags for Shopify filtering + later reporting."""
    out: list[str] = []
    for key in ("drop", "style", "tone", "vibe"):
        val = (r.get(key) or "").strip()
        if val:
            out.append(f"{key}:{slugify(val)}")
    mn = (r.get("micro_niche") or "").strip()
    if mn:
        out.append(f"micro:{slugify(mn)}")
    return out


def _risk_check_row(r: dict) -> tuple[str, str]:
    combined = " | ".join(
        [
            r.get("phrase", "") or "",
            r.get("niche", "") or "",
            r.get("tags", "") or "",
            r.get("motif", "") or "",
            r.get("drop", "") or "",
        ]
    )
    reason = detect_risk(combined)
    if reason:
        return "REVIEW", reason
    return "SAFE", ""


def _brief_context_from_row(r: dict) -> dict:
    """
    Deterministic Option B context: forces prompt builder to use the row fields.
    """
    return {
        "motif": r.get("motif", "") or "",
        "phrase": r.get("phrase", "") or "",
        "drop_title": r.get("drop_title", "") or "",
        "vibe": r.get("vibe", "") or "",
        "tone": r.get("tone", "") or "",
        "palette_hint": r.get("palette_hint", "") or "",
        "embroidery_style": r.get("embroidery_style", "") or "",
        "embroidery_focus": r.get("embroidery_focus", "") or "",
        "micro_niche": r.get("micro_niche", "") or "",
        "object_state": r.get("object_state", "") or "",
        "era_situation": r.get("era_situation", "") or "",
        "texture_cue": r.get("texture_cue", "") or "",
        "variation_modifier": r.get("variation_modifier", "") or "",
        "motif_family": r.get("motif_family", "") or "",
        "motif_frame": r.get("motif_frame", "") or "",
        "motif_keywords": r.get("motif_keywords", "") or "",
        "center_weight": r.get("center_weight", "") or "",
        "silhouette_strength": r.get("silhouette_strength", "") or "",
        # style is handled separately by design_factory via `style=` arg and/or brief.style
    }


# ----------------------------
# Seeding
# ----------------------------
def seed_queue(rows, count: int, *, drop: str = "", include_text: bool = False):
    """
    Appends NEW rows to the queue for hats (Option B).
    Seeds stable V4 fields into queue.csv so human review is consistent.
    """
    if count <= 0:
        return rows

    max_id = 0
    for r in rows:
        try:
            max_id = max(max_id, int((r.get("id") or "0").strip()))
        except Exception:
            pass

    for i in range(1, count + 1):
        new_id = str(max_id + i)

        brief = pick_brief(drop=drop or None, include_text=include_text)

        # Use V4’s weighted style (do NOT randomize here) – but keep fallback
        style = getattr(brief, "style", "") or random.choice(STYLE_CHOICES)

        drop_slug = getattr(brief, "drop", "") or ""
        base_tags = [
            "90s nostalgia",
            "retro hat",
            "embroidered cap",
            "millennial gift",
            "minimalist retro",
            f"drop:{drop_slug}" if drop_slug else "",
        ]
        tags_str = ",".join([t for t in base_tags if t])

        rows.append(
            {
                "id": new_id,
                "status": "NEW",
                "product_type": "hat",
                "drop": getattr(brief, "drop", ""),
                "drop_title": getattr(brief, "drop_title", ""),
                "motif": getattr(brief, "motif", ""),
                "vibe": getattr(brief, "vibe", ""),
                "tone": getattr(brief, "tone", ""),
                "palette_hint": getattr(brief, "palette_hint", ""),
                "embroidery_style": getattr(brief, "embroidery_style", ""),
                "embroidery_focus": getattr(brief, "embroidery_focus", ""),
                "micro_niche": getattr(brief, "micro_niche", ""),
                "object_state": getattr(brief, "object_state", ""),
                "era_situation": getattr(brief, "era_situation", ""),
                "texture_cue": getattr(brief, "texture_cue", ""),
                "variation_modifier": getattr(brief, "variation_modifier", ""),
                "motif_family": getattr(brief, "motif_family", ""),
                "motif_frame": getattr(brief, "motif_frame", ""),
                "motif_keywords": getattr(brief, "motif_keywords", ""),
                "center_weight": getattr(brief, "center_weight", ""),
                "silhouette_strength": getattr(brief, "silhouette_strength", ""),
                "product_rules": "hat_front:1200x675@300dpi|safe:3.5x2.0in|max_colors:6",
                "style": style,
                "include_text": "YES" if include_text else "NO",
                "phrase": getattr(brief, "phrase", "") if include_text else "",
                "niche": "90s nostalgia",
                "tags": tags_str,
                "placement": "front",
                "risk_flag": "SAFE",
                "policy_status": "",
                "risk_reason": "",
                "prompt_debug": "",
                "prompt_hash": "",
                "resolved_style": "",
                "quality_status": "",
                "quality_reason": "",
                "quality_json": "",
                "drop_seq": "",
                "local_path": "",
                "generated_at": "",
                "approved_at": "",
                "printify_product_id": "",
                "published_at": "",
                "r2_url": "",
                "mockup_r2_url": "",
                "printify_image_id": "",
            }
        )

    return rows


# ----------------------------
# Generate-only mode (human review)
# ----------------------------
def generate_batch(n: int, *, drop_filter: str = "") -> tuple[int, int]:
    """Generate images for the next N NEW rows and stop (no upload/publish)."""
    load_dotenv()
    rows = load_queue()
    out_dir = os.getenv("OUT_DIR", "out")
    os.makedirs(out_dir, exist_ok=True)

    want_prompt = _env_true("PROMPT_DEBUG", "0")

    generated = 0
    failed = 0
    for idx, r in enumerate(rows):
        if generated >= n:
            break

        status = (r.get("status", "") or "").strip().upper()
        if status != "NEW":
            continue

        if drop_filter and (r.get("drop") or "").strip() != drop_filter:
            continue

        rid = (r.get("id") or "").strip() or str(idx + 1)
        product_type = (r.get("product_type") or "hat").strip().lower()
        style = (r.get("style") or "ai_art").strip().lower()
        placement = (r.get("placement") or "front").strip().lower()
        drop = (r.get("drop") or "").strip()
        motif = (r.get("motif") or "").strip()
        include_text = (r.get("include_text") or "NO").strip().upper() in ("YES", "TRUE", "1")

        # keep phrase stable if seeded; only fill if missing and include_text
        phrase = (r.get("phrase") or "").strip()
        if include_text and not phrase:
            try:
                phrase = pick_phrase("90s nostalgia")
                r["phrase"] = phrase
            except Exception as e:
                r["status"] = "HOLD_ERROR"
                r["risk_reason"] = f"phrase_error:{type(e).__name__}:{e}"
                rows[idx] = r
                failed += 1
                continue

        # concept gate (embroidery-first)
        try:
            brief_gate = brief_from_row(r, include_text=include_text)
            concept_ok, concept_reasons = evaluate_embroidery_concept(brief_gate, product_type=product_type)
            if not concept_ok:
                r["quality_status"] = "FAIL"
                r["quality_reason"] = "concept:" + ",".join(concept_reasons)
                r["status"] = "HOLD_QUALITY"
                rows[idx] = r
                failed += 1
                continue
        except Exception as e:
            r["quality_status"] = "FAIL"
            r["quality_reason"] = f"concept_error:{type(e).__name__}"
            r["status"] = "HOLD_QUALITY"
            rows[idx] = r
            failed += 1
            continue

        # risk gate
        risk_flag, risk_reason = _risk_check_row(r)
        r["risk_flag"] = risk_flag
        r["risk_reason"] = risk_reason
        if risk_flag == "REVIEW" and (r.get("policy_status", "") or "").strip().upper() != "APPROVED":
            r["status"] = "HOLD"
            rows[idx] = r
            failed += 1
            continue

        drop_display = get_drop_title(drop) if drop else ""
        title = build_title(
            "",
            product_type=product_type,
            drop=drop_display,
            motif_hint=("Loading" if "loading" in motif.lower() else None),
        )

        # ALWAYS define img; never crash the batch
        try:
            img, prompt_debug = build_design(
                style=style,
                title=title,
                phrase=phrase,
                niche="90s nostalgia",
                placement=placement,
                product_type=product_type,
                drop=drop or None,
                include_text=include_text,
                brief_context=_brief_context_from_row(r),
                return_prompt=True,
            )
        except Exception as e:
            r["status"] = "HOLD_ERROR"
            r["risk_reason"] = f"gen_error:{type(e).__name__}:{e}"
            rows[idx] = r
            failed += 1
            continue

        # prompt logging
        if want_prompt:
            try:
                r["prompt_debug"] = json.dumps({
                    "prompt": prompt_debug,
                    "product_type": product_type,
                    "drop": drop,
                    "motif": motif,
                    "style": style,
                    "motif_family": r.get("motif_family", ""),
                    "motif_frame": r.get("motif_frame", ""),
                    "motif_keywords": r.get("motif_keywords", ""),
                }, ensure_ascii=False)
            except Exception:
                r["prompt_debug"] = prompt_debug
        r["prompt_hash"] = _sha1(prompt_debug)

        # resolved style bookkeeping (best-effort; design_factory resolves internally)
        r["resolved_style"] = (r.get("style") or "").strip().lower()

        # quality gate
        ok, q_reason, q_json = pass_fail(img)
        r["quality_status"] = "PASS" if ok else "FAIL"
        r["quality_reason"] = q_reason or ""
        try:
            r["quality_json"] = json.dumps(q_json)
        except Exception:
            r["quality_json"] = str(q_json)

        if not ok:
            r["status"] = "HOLD_QUALITY"
            rows[idx] = r
            failed += 1
            continue

        filename = f"{rid}_{slugify(drop)}_{slugify(motif) or 'design'}.png"
        local_path = os.path.join(out_dir, filename)
        img.save(local_path, "PNG")

        r["local_path"] = local_path
        r["generated_at"] = datetime.now(timezone.utc).isoformat()
        r["status"] = "GENERATED"
        rows[idx] = r
        generated += 1

    save_queue(rows)
    return generated, failed


def verify_generated(*, prune_missing: bool = True) -> tuple[int, int, int]:
    """Verify GENERATED rows by checking whether local_path still exists."""
    load_dotenv()
    rows = load_queue()

    approved = 0
    rejected = 0
    checked = 0

    new_rows = []
    for r in rows:
        status = (r.get("status", "") or "").strip().upper()
        if status != "GENERATED":
            new_rows.append(r)
            continue

        checked += 1
        path = (r.get("local_path") or "").strip()
        if path and os.path.exists(path):
            r["status"] = "APPROVED"
            r["approved_at"] = datetime.now(timezone.utc).isoformat()
            new_rows.append(r)
            approved += 1
        else:
            rejected += 1
            if prune_missing:
                continue
            r["status"] = "REJECTED"
            new_rows.append(r)

    save_queue(new_rows)
    return checked, approved, rejected


# ----------------------------
# Publish one
# ----------------------------
def process_one(*, auto_seed: bool = True) -> bool:
    load_dotenv()
    rows = load_queue()

    target_idx = pick_next_row_index(rows)

    # Auto-seed only if queue has nothing publishable
    if target_idx is None and auto_seed:
        names = get_drop_names()
        per = max(1, int(AUTO_SEED_IF_EMPTY / max(1, len(names))))
        remaining = AUTO_SEED_IF_EMPTY
        for dn in names:
            n = min(per, remaining)
            rows = seed_queue(rows, n, drop=dn)
            remaining -= n
        while remaining > 0:
            rows = seed_queue(rows, 1, drop=random.choice(names))
            remaining -= 1
        save_queue(rows)
        target_idx = pick_next_row_index(rows)

    if target_idx is None:
        log("✅ No publishable NEW/APPROVED rows.")
        return False

    r = rows[target_idx]
    rid = (r.get("id") or "").strip() or str(target_idx + 1)

    product_type = (r.get("product_type") or "hat").strip().lower()
    style = (r.get("style") or "ai_art").strip().lower()
    placement = (r.get("placement") or "front").strip().lower()
    drop = (r.get("drop") or "").strip()
    motif = (r.get("motif") or "").strip()
    include_text = (r.get("include_text") or "NO").strip().upper() in ("YES", "TRUE", "1")

    phrase = (r.get("phrase") or "").strip()
    if include_text and not phrase:
        phrase = pick_phrase("90s nostalgia")
        r["phrase"] = phrase

    # concept gate (embroidery-first)
    try:
        brief_gate = brief_from_row(r, include_text=include_text)
        concept_ok, concept_reasons = evaluate_embroidery_concept(brief_gate, product_type=product_type)
        if not concept_ok:
            r["quality_status"] = "FAIL"
            r["quality_reason"] = "concept:" + ",".join(concept_reasons)
            r["status"] = "HOLD_QUALITY"
            rows[target_idx] = r
            save_queue(rows)
            log(f"🟨 Row {rid} failed concept gate: {r['quality_reason']}")
            return False
    except Exception as e:
        r["quality_status"] = "FAIL"
        r["quality_reason"] = f"concept_error:{type(e).__name__}"
        r["status"] = "HOLD_QUALITY"
        rows[target_idx] = r
        save_queue(rows)
        log(f"🟨 Row {rid} concept gate errored: {e}")
        return False

    # Risk gate
    risk_flag, risk_reason = _risk_check_row(r)
    r["risk_flag"] = risk_flag
    r["risk_reason"] = risk_reason
    if risk_flag == "REVIEW" and (r.get("policy_status", "") or "").strip().upper() != "APPROVED":
        r["status"] = "HOLD"
        rows[target_idx] = r
        save_queue(rows)
        log(f"🟨 Row {rid} flagged for REVIEW: {risk_reason}. Set policy_status=APPROVED to proceed.")
        return False

    # Drop limit gate BEFORE spending money/time
    limit = get_drop_limited(drop) if drop else 0
    if drop and limit and not can_publish(drop, limit):
        r["status"] = "SOLD_OUT"
        rows[target_idx] = r
        save_queue(rows)
        log(f"🟥 Drop limit reached for {drop} (limit={limit}). Row {rid} marked SOLD_OUT.")
        return False

    drop_display = get_drop_title(drop) if drop else ""
    title = build_title(
        "",
        product_type=product_type,
        drop=drop_display,
        motif_hint=("Loading" if "loading" in motif.lower() else None),
    )

    description = build_description(
        title,
        "90s nostalgia",
        product_type=product_type,
        drop=drop_display,
        motif=motif,
        limited_count=get_drop_limited(drop) if drop else 0,
    )

    tags = [t.strip() for t in (r.get("tags") or "").split(",") if t.strip()]
    tags = tags + ["no filter", "nofilter", "90s"] + build_drop_tags(drop) + _analytics_tags(r)

    # Build design + prompt hash + quality gate
    want_prompt = _env_true("PROMPT_DEBUG", "0")
    try:
        img, prompt_debug = build_design(
            style=style,
            title=title,
            phrase=phrase,
            niche="90s nostalgia",
            placement=placement,
            product_type=product_type,
            drop=drop or None,
            include_text=include_text,
            brief_context=_brief_context_from_row(r),
            return_prompt=True,
        )
    except Exception as e:
        r["status"] = "HOLD_ERROR"
        r["risk_reason"] = f"gen_error:{type(e).__name__}:{e}"
        rows[target_idx] = r
        save_queue(rows)
        log(f"🟥 Row {rid} generation failed: {e}")
        return False

    if want_prompt:
        r["prompt_debug"] = prompt_debug
    r["prompt_hash"] = _sha1(prompt_debug)
    r["resolved_style"] = (r.get("style") or "").strip().lower()

    ok, q_reason, q_json = pass_fail(img)
    r["quality_status"] = "PASS" if ok else "FAIL"
    r["quality_reason"] = q_reason or ""
    try:
        r["quality_json"] = json.dumps(q_json)
    except Exception:
        r["quality_json"] = str(q_json)

    if not ok:
        r["status"] = "HOLD_QUALITY"
        rows[target_idx] = r
        save_queue(rows)
        log(f"🟨 Row {rid} failed quality gate: {q_reason}.")
        return False

    # Save locally
    out_dir = os.getenv("OUT_DIR", "out")
    os.makedirs(out_dir, exist_ok=True)
    filename = f"{rid}_{slugify(drop)}_{slugify(motif) or 'design'}.png"
    local_path = os.path.join(out_dir, filename)
    img.save(local_path, "PNG")
    r["local_path"] = local_path

    # Upload to R2
    r2_url = upload_file(local_path, key=f"nofilter/hats/{filename}")
    r["r2_url"] = r2_url

    # Optional mockup
    if _env_true("MAKE_MOCKUPS", "0"):
        try:
            mock = make_simple_hat_mockup(img)
            mock_name = filename.replace(".png", "_mockup.png")
            mock_path = os.path.join(out_dir, mock_name)
            mock.save(mock_path, "PNG")
            mock_url = upload_file(mock_path, key=f"nofilter/mockups/{mock_name}")
            r["mockup_r2_url"] = mock_url
        except Exception as e:
            log(f"🟨 Mockup step skipped: {e}")

    # Push to Printify + publish
    blueprint_id = find_hat_blueprint()
    provider_id = pick_print_provider(blueprint_id)
    variants = get_variants(blueprint_id, provider_id)

    # choose_hat_variant_ids may or may not support seed_key; do both safely
    try:
        variant_ids = choose_hat_variant_ids(variants, seed_key=f"{rid}|{title}")
    except TypeError:
        variant_ids = choose_hat_variant_ids(variants)

    price_usd = float(os.getenv("HAT_PRICE_USD", "34.00"))
    price_cents = int(round(price_usd * 100))

    shop_id = get_shop_id()
    printify_image_id = upload_image_by_url(filename, r2_url)
    r["printify_image_id"] = printify_image_id

    product_id = create_hat_product(
        shop_id=shop_id,
        title=title,
        description=description,
        tags=tags,
        blueprint_id=blueprint_id,
        provider_id=provider_id,
        variant_ids=variant_ids,
        image_id=printify_image_id,
        price_cents=price_cents,
    )

    publish_product(shop_id, product_id)

    r["printify_product_id"] = str(product_id)

    if drop:
        try:
            r["drop_seq"] = str(increment(drop))
        except Exception:
            pass

    r["published_at"] = datetime.now(timezone.utc).isoformat()
    r["status"] = "PUBLISHED"

    rows[target_idx] = r
    save_queue(rows)

    log(f"✅ Published hat: row={rid} product_id={product_id}")
    return True


# ----------------------------
# CLI
# ----------------------------
def main():
    ap = argparse.ArgumentParser(description="NoFilterCo queue runner (hats / nostalgia)")
    ap.add_argument("--seed", type=int, default=0, help="Add N NEW hat rows to queue.csv")
    ap.add_argument("--drop", type=str, default="", help="Optional drop slug (see drops.yaml)")
    ap.add_argument("--drop_mode", action="store_true", help="If seeding, rotate evenly across all drops instead of a single drop")
    ap.add_argument("--include_text", action="store_true", help="If set, include short safe text on the hat design")
    ap.add_argument("--generate_batch", type=int, default=0, help="Generate N images only (no upload/publish). Rows become status=GENERATED")
    ap.add_argument("--verify_generated", action="store_true", help="Approve GENERATED rows if local_path exists; prune missing by default")
    ap.add_argument("--keep_rejected", action="store_true", help="With --verify_generated: keep rejected rows (status=REJECTED) instead of removing")
    ap.add_argument("--once", action="store_true", help="Process a single publishable row and exit")
    ap.add_argument("--loop", action="store_true", help="Keep processing until no publishable rows remain")
    ap.add_argument("--run_all", action="store_true", help="Alias for --loop")
    args = ap.parse_args()

    load_dotenv()
    rows = load_queue()

    # 1) Generate-only mode (human review workflow)
    if args.generate_batch and args.generate_batch > 0:
        generated, failed = generate_batch(args.generate_batch, drop_filter=args.drop)
        log(f"✅ Generate pass complete: generated={generated} failed={failed}.")
        log("\nNext:\n  - Manually delete any bad PNGs from your OUT_DIR folder (default: ./out)")
        log("  - Then run: python run_queue.py --verify_generated")
        return

    # 2) Verification mode
    if args.verify_generated:
        checked, approved, rejected = verify_generated(prune_missing=not args.keep_rejected)
        log(f"✅ Verify pass complete: checked={checked} approved={approved} rejected={rejected}.")
        log("Now publish with: python run_queue.py --once   (or --run_all)")
        return

    # 3) Seeding
    if args.seed > 0:
        if args.drop_mode:
            names = get_drop_names()
            per = max(1, int(args.seed / max(1, len(names))))
            remaining = args.seed
            for dn in names:
                n = min(per, remaining)
                rows = seed_queue(rows, n, drop=dn, include_text=args.include_text)
                remaining -= n
            while remaining > 0:
                rows = seed_queue(rows, 1, drop=random.choice(names), include_text=args.include_text)
                remaining -= 1
        else:
            rows = seed_queue(rows, args.seed, drop=args.drop, include_text=args.include_text)

        save_queue(rows)
        log(f"✅ Seeded {args.seed} rows.")
        if args.once or not args.loop:
            return

    if args.run_all:
        args.loop = True

    # 4) Loop publish mode
    if args.loop:
        published = 0
        stopped = 0
        while True:
            did = process_one(auto_seed=False)
            if not did:
                stopped += 1
                break
            published += 1
        log(f"✅ Publish pass complete: published={published} stop_events={stopped}.")
        return

    # default: publish once (auto seed if queue empty)
    process_one(auto_seed=True)


if __name__ == "__main__":
    main()
