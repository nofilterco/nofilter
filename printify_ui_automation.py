from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from catalog_queue import load_rows, save_rows


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


SYNC_DETAIL_LABELS = {
    "product_title": "Product title",
    "description": "Description",
    "mockups": "Mockups",
    "colors_sizes_prices_skus": "Colors, sizes, prices, SKUs",
    "tags": "Tags",
    "shipping_profile": "Shipping profile",
}


@dataclass
class AutomationTarget:
    row_id: str
    listing_slug: str
    printify_product_id: str
    should_enable_personalization: bool
    personalization_toggle_manual_required: bool
    printify_personalize_button_required: bool
    editable_fields_summary: str
    supports_text_edit: bool
    supports_photo_upload: bool
    supports_logo_upload: bool
    variant_visibility_recommended: str
    sync_details_recommended: list[str]
    packet_path: str


def _truthy(value: str) -> bool:
    return str(value or "").strip().upper() in {"YES", "TRUE", "1"}


def _load_checklist_rows(path: str) -> dict[str, dict[str, str]]:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8", newline="") as f:
        return {r.get("id", ""): r for r in csv.DictReader(f) if r.get("id")}


def _load_setup_packet(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _parse_sync_details(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            val = json.loads(text)
            if isinstance(val, list):
                return [str(v).strip() for v in val if str(v).strip()]
        except Exception:
            pass
    return [v.strip() for v in text.split(",") if v.strip()]


def _resolve_targets(
    rows: list[dict[str, str]],
    checklist_rows: dict[str, dict[str, str]],
    *,
    listing_slugs: set[str],
    row_ids: set[str],
    manual_required_synced_only: bool,
) -> list[AutomationTarget]:
    out: list[AutomationTarget] = []
    for row in rows:
        if listing_slugs and row.get("listing_slug") not in listing_slugs:
            continue
        if row_ids and row.get("id") not in row_ids:
            continue
        if manual_required_synced_only:
            if row.get("shopify_sync_status") != "SYNCED_TO_SHOPIFY":
                continue
            if not _truthy(row.get("needs_manual_personalization_setup", "NO")):
                continue
        if not (listing_slugs or row_ids or manual_required_synced_only):
            continue

        checklist = checklist_rows.get(row.get("id", ""), {})
        packet_path = row.get("manual_setup_packet_path") or checklist.get("manual_setup_packet_path") or ""
        packet = _load_setup_packet(packet_path)
        readiness = packet.get("personalization_hub_readiness") if isinstance(packet, dict) else {}
        if not isinstance(readiness, dict):
            readiness = {}

        sync_raw = (
            row.get("sync_details_recommended")
            or checklist.get("sync_details_recommended")
            or ",".join(packet.get("recommended_sync_detail_selections", []))
        )

        out.append(
            AutomationTarget(
                row_id=row.get("id", ""),
                listing_slug=row.get("listing_slug", ""),
                printify_product_id=row.get("printify_product_id", ""),
                should_enable_personalization=_truthy(
                    row.get("should_enable_personalization")
                    or checklist.get("should_enable_personalization")
                    or readiness.get("should_enable_personalization", "NO")
                ),
                personalization_toggle_manual_required=_truthy(
                    row.get("personalization_toggle_manual_required")
                    or checklist.get("personalization_toggle_manual_required")
                    or readiness.get("personalization_toggle_manual_required", "NO")
                ),
                printify_personalize_button_required=_truthy(
                    row.get("printify_personalize_button_required")
                    or checklist.get("printify_personalize_button_required")
                    or readiness.get("printify_personalize_button_required", "NO")
                ),
                editable_fields_summary=row.get("editable_fields_summary") or checklist.get("editable_fields_summary", ""),
                supports_text_edit=_truthy(row.get("supports_text_edit") or checklist.get("supports_text_edit")),
                supports_photo_upload=_truthy(row.get("supports_photo_upload") or checklist.get("supports_photo_upload")),
                supports_logo_upload=_truthy(row.get("supports_logo_upload") or checklist.get("supports_logo_upload")),
                variant_visibility_recommended=(
                    row.get("variant_visibility_recommended")
                    or checklist.get("variant_visibility_recommended")
                    or packet.get("recommended_variant_visibility_setting", "")
                ),
                sync_details_recommended=_parse_sync_details(sync_raw),
                packet_path=packet_path,
            )
        )
    return out


def _product_url(product_id: str) -> str:
    return f"https://printify.com/app/products/{product_id}"


def _wait_for_enter(message: str) -> None:
    print(message)
    try:
        input()
    except EOFError:
        pass


def _ensure_out_dirs() -> tuple[Path, Path]:
    root = Path("out/printify_ui_automation")
    shots = root / "screenshots"
    root.mkdir(parents=True, exist_ok=True)
    shots.mkdir(parents=True, exist_ok=True)
    return root, shots


def _write_shopify_theme_checklist(path: Path) -> str:
    checklist = path / "shopify_theme_personalize_button_checklist.md"
    if checklist.exists():
        return str(checklist)
    checklist.write_text(
        "# Shopify Theme Personalization Checklist\n\n"
        "This helper is intentionally manual-first (Phase 8 safety scope).\n\n"
        "- [ ] Open Shopify Online Store > Themes > Customize.\n"
        "- [ ] Open the default product template used by Crafted Occasion products.\n"
        "- [ ] Confirm the **Printify Personalize Button** app block exists.\n"
        "- [ ] Ensure the app block is visible above Add to cart or in your intended section.\n"
        "- [ ] Save the theme and verify at least one synced personalized product page in storefront view.\n"
        "- [ ] If missing, add the block and re-test before bulk republish.\n",
        encoding="utf-8",
    )
    return str(checklist)


def run_ui_automation(args: argparse.Namespace) -> dict[str, Any]:
    rows = load_rows()
    checklist = _load_checklist_rows(args.checklist_csv)
    targets = _resolve_targets(
        rows,
        checklist,
        listing_slugs=set(args.listing_slug or []),
        row_ids=set(args.row_id or []),
        manual_required_synced_only=args.manual_required_synced_only,
    )
    if not targets:
        raise ValueError("No targets found. Provide --listing-slug / --row-id / --manual-required-synced-only.")

    output_root, shots_root = _ensure_out_dirs()
    theme_checklist_path = _write_shopify_theme_checklist(output_root)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_rows: list[dict[str, Any]] = []

    if args.dry_run and args.screenshot_only:
        mode = "dry_run_screenshot_only"
    elif args.dry_run:
        mode = "dry_run"
    else:
        mode = "live"

    page = context = browser = playwright = None
    if not args.plan_only:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("Playwright is required. Install with `pip install playwright` and `playwright install chromium`.") from exc

        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=args.headless)
        context_kwargs: dict[str, Any] = {}
        if args.storage_state and Path(args.storage_state).exists():
            context_kwargs["storage_state"] = args.storage_state
        context = browser.new_context(**context_kwargs)
        page = context.new_page()

    try:
        for t in targets[: args.limit or len(targets)]:
            started = now_iso()
            action_log: list[dict[str, Any]] = []
            screenshot_paths: list[str] = []
            status = "skipped"
            result = "no_actions"
            diag = ""
            try:
                if not t.printify_product_id:
                    raise RuntimeError("Missing printify_product_id")
                product_url = _product_url(t.printify_product_id)
                action_log.append({"ts": now_iso(), "step": "target_loaded", "detail": {"url": product_url, "mode": mode}})

                if args.plan_only:
                    status = "planned"
                    result = "plan_generated"
                else:
                    before = shots_root / f"{run_id}_{t.listing_slug}_before.png"
                    page.goto(product_url, wait_until="domcontentloaded", timeout=args.timeout_ms)
                    page.screenshot(path=str(before), full_page=True)
                    screenshot_paths.append(str(before))

                    personalization_toggle = page.locator('label:has-text("Personalization"), text=/Enable personalization/i').first
                    publish_section = page.locator('text=/Publishing settings|Select details for sync|Publish/i').first
                    has_toggle = personalization_toggle.count() > 0
                    has_publish = publish_section.count() > 0
                    action_log.append({"ts": now_iso(), "step": "selector_probe", "detail": {"has_personalization_toggle": has_toggle, "has_publish_area": has_publish}})
                    if not has_publish:
                        raise RuntimeError("Could not locate publishing/selective sync area safely")

                    if has_toggle and t.should_enable_personalization and not args.screenshot_only:
                        try:
                            aria = personalization_toggle.get_attribute("aria-checked")
                            checked = str(aria).lower() == "true"
                        except Exception:
                            checked = False
                        action_log.append({"ts": now_iso(), "step": "personalization_state", "detail": {"is_enabled": checked}})
                        if not checked:
                            personalization_toggle.click(timeout=args.timeout_ms)
                            action_log.append({"ts": now_iso(), "step": "personalization_enabled", "detail": "toggle_clicked"})

                    if t.variant_visibility_recommended == "in_stock_only":
                        action_log.append({"ts": now_iso(), "step": "variant_visibility_recommended", "detail": "in_stock_only"})
                        if not args.screenshot_only:
                            in_stock_option = page.locator('text=/In stock only/i').first
                            if in_stock_option.count() > 0:
                                in_stock_option.click(timeout=2000)
                                action_log.append({"ts": now_iso(), "step": "variant_visibility_set", "detail": "in_stock_only_clicked"})

                    for detail in t.sync_details_recommended:
                        label = SYNC_DETAIL_LABELS.get(detail, detail)
                        box = page.locator(f'label:has-text("{label}"), text=/{label}/i').first
                        found = box.count() > 0
                        action_log.append({"ts": now_iso(), "step": "sync_detail_probe", "detail": {"detail": detail, "label": label, "found": found}})
                        if found and not args.screenshot_only:
                            try:
                                box.click(timeout=2000)
                                action_log.append({"ts": now_iso(), "step": "sync_detail_checked", "detail": detail})
                            except Exception:
                                action_log.append({"ts": now_iso(), "step": "sync_detail_check_failed", "detail": detail})

                    if args.confirm_each and not args.headless:
                        _wait_for_enter(f"Review product {t.listing_slug} in browser; press Enter to continue...")

                    if not args.dry_run and not args.screenshot_only:
                        publish_btn = page.locator('button:has-text("Republish"), button:has-text("Publish")').first
                        if publish_btn.count() == 0:
                            raise RuntimeError("Publish/Republish button not found")
                        publish_btn.click(timeout=args.timeout_ms)
                        action_log.append({"ts": now_iso(), "step": "publish_clicked", "detail": "publish_or_republish"})

                    after = shots_root / f"{run_id}_{t.listing_slug}_after.png"
                    page.screenshot(path=str(after), full_page=True)
                    screenshot_paths.append(str(after))
                    status = "completed"
                    result = "dry_run_complete" if args.dry_run else "live_complete"

            except Exception as exc:
                status = "failed"
                result = "selector_or_runtime_failure"
                diag = str(exc)
                action_log.append({"ts": now_iso(), "step": "error", "detail": diag})

            row_record = {
                "id": t.row_id,
                "listing_slug": t.listing_slug,
                "printify_product_id": t.printify_product_id,
                "mode": mode,
                "started_at": started,
                "finished_at": now_iso(),
                "ui_automation_status": status,
                "ui_automation_last_result": result if not diag else f"{result}: {diag}",
                "ui_automation_screenshot_paths": screenshot_paths,
                "action_log": action_log,
            }
            report_rows.append(row_record)

            for row in rows:
                if row.get("id") == t.row_id:
                    row["ui_automation_status"] = status
                    row["ui_automation_last_run_at"] = row_record["finished_at"]
                    row["ui_automation_last_result"] = row_record["ui_automation_last_result"]
                    row["ui_automation_screenshot_paths"] = json.dumps(screenshot_paths)
                    break

    finally:
        if context is not None:
            context.close()
        if browser is not None:
            browser.close()
        if playwright is not None:
            playwright.stop()

    save_rows(rows)

    report_json = output_root / f"ui_automation_report_{run_id}.json"
    report_csv = output_root / f"ui_automation_report_{run_id}.csv"
    report_json.write_text(json.dumps({"run_id": run_id, "mode": mode, "theme_checklist": theme_checklist_path, "rows": report_rows}, indent=2), encoding="utf-8")

    with report_csv.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "id",
            "listing_slug",
            "printify_product_id",
            "mode",
            "started_at",
            "finished_at",
            "ui_automation_status",
            "ui_automation_last_result",
            "ui_automation_screenshot_paths",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in report_rows:
            writer.writerow({k: (json.dumps(row.get(k, [])) if k == "ui_automation_screenshot_paths" else row.get(k, "")) for k in fieldnames})

    return {
        "run_id": run_id,
        "mode": mode,
        "targets": len(report_rows),
        "report_json": str(report_json),
        "report_csv": str(report_csv),
        "theme_checklist": theme_checklist_path,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Printify UI automation helper (Phase 8)")
    p.add_argument("--listing-slug", action="append", default=[])
    p.add_argument("--row-id", action="append", default=[])
    p.add_argument("--manual-required-synced-only", action="store_true")
    p.add_argument("--checklist-csv", default="shopify_personalization_setup_checklist.csv")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--screenshot-only", action="store_true")
    p.add_argument("--plan-only", action="store_true", help="No browser actions; still produces target plan report")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--confirm-each", action="store_true")
    p.add_argument("--storage-state", default="")
    p.add_argument("--timeout-ms", type=int, default=15000)
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()

    result = run_ui_automation(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
