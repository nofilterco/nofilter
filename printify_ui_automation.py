from __future__ import annotations

import argparse
import csv
import json
import time
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

AUTH_HELP_MESSAGE = (
    "Authentication appears to be missing/expired. Bootstrap a reusable Chrome session first: "
    "--bootstrap-login --channel chrome --user-data-dir local_artifacts/printify_chrome_profile"
)


class SelectorNotFoundError(RuntimeError):
    """Raised when no selector strategy matched for a required UI element."""

    def __init__(self, key: str, attempts: list[dict[str, Any]]):
        super().__init__(f"No selector matched for '{key}'")
        self.key = key
        self.attempts = attempts


def _safe_count(locator: Any) -> int:
    try:
        return locator.count()
    except Exception:
        return 0


def _selector_probe(page: Any, key: str, strategies: list[dict[str, Any]], *, required: bool = False) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for strategy in strategies:
        name = strategy.get("name", "unnamed")
        factory = strategy.get("locator")
        if not callable(factory):
            attempts.append({"strategy": name, "matched": False, "error": "locator_factory_missing"})
            continue
        try:
            loc = factory(page)
            count = _safe_count(loc)
            matched = count > 0
            attempt: dict[str, Any] = {"strategy": name, "matched": matched, "count": count}
            if matched:
                attempt["selected"] = True
                attempts.append(attempt)
                return {"key": key, "matched": True, "selected_strategy": name, "locator": loc, "attempts": attempts}
            attempts.append(attempt)
        except Exception as exc:
            attempts.append({"strategy": name, "matched": False, "error": str(exc)})

    if required:
        raise SelectorNotFoundError(key, attempts)
    return {"key": key, "matched": False, "selected_strategy": None, "locator": None, "attempts": attempts}


def _personalization_toggle_probe(page: Any) -> dict[str, Any]:
    return _selector_probe(
        page,
        "personalization_toggle",
        [
            {"name": "primary_css_label_text", "locator": lambda p: p.locator('label:has-text("Personalization")').first},
            {"name": "secondary_text_regex", "locator": lambda p: p.get_by_text("Enable personalization", exact=False).first},
            {"name": "text_based_any", "locator": lambda p: p.locator("text=/personalization/i").first},
            {"name": "role_switch_name", "locator": lambda p: p.get_by_role("switch", name="Personalization", exact=False).first},
        ],
    )


def _variant_visibility_probe(page: Any) -> dict[str, Any]:
    return _selector_probe(
        page,
        "variant_visibility_in_stock_only",
        [
            {"name": "primary_text_exact", "locator": lambda p: p.get_by_text("In stock only", exact=False).first},
            {"name": "secondary_label", "locator": lambda p: p.get_by_label("In stock only", exact=False).first},
            {"name": "text_regex", "locator": lambda p: p.locator("text=/in stock only/i").first},
            {"name": "role_radio", "locator": lambda p: p.get_by_role("radio", name="In stock only", exact=False).first},
        ],
    )


def _sync_detail_probe(page: Any, label: str) -> dict[str, Any]:
    return _selector_probe(
        page,
        f"sync_detail_{label}",
        [
            {"name": "primary_label_text", "locator": lambda p: p.locator(f'label:has-text("{label}")').first},
            {"name": "secondary_get_by_label", "locator": lambda p: p.get_by_label(label, exact=False).first},
            {"name": "text_based", "locator": lambda p: p.get_by_text(label, exact=False).first},
            {"name": "role_checkbox", "locator": lambda p: p.get_by_role("checkbox", name=label, exact=False).first},
        ],
    )


def _publish_area_probe(page: Any) -> dict[str, Any]:
    return _selector_probe(
        page,
        "publish_area",
        [
            {"name": "primary_text_publish_settings", "locator": lambda p: p.get_by_text("Publishing settings", exact=False).first},
            {"name": "secondary_text_select_sync", "locator": lambda p: p.get_by_text("Select details for sync", exact=False).first},
            {"name": "text_regex_publish", "locator": lambda p: p.locator("text=/Publishing settings|Select details for sync|Publish/i").first},
            {"name": "role_heading_publish", "locator": lambda p: p.get_by_role("heading", name="Publish", exact=False).first},
        ],
        required=True,
    )


def _publish_button_probe(page: Any) -> dict[str, Any]:
    return _selector_probe(
        page,
        "publish_button",
        [
            {"name": "primary_republish", "locator": lambda p: p.get_by_role("button", name="Republish", exact=False).first},
            {"name": "secondary_publish", "locator": lambda p: p.get_by_role("button", name="Publish", exact=False).first},
            {"name": "text_button_regex", "locator": lambda p: p.locator("button:has-text('Republish')").first},
            {"name": "text_based_fallback", "locator": lambda p: p.locator("text=/Republish|Publish/i").first},
        ],
        required=True,
    )


def _auth_probe(page: Any) -> dict[str, Any]:
    final_url = ""
    try:
        final_url = str(page.url or "")
    except Exception:
        final_url = ""

    url_lower = final_url.lower()
    if any(token in url_lower for token in ("/login", "signin", "auth", "oauth")):
        return {"matched": True, "reason": "url_login_pattern", "final_url": final_url}

    login_probe = _selector_probe(
        page,
        "auth_gate",
        [
            {"name": "email_input", "locator": lambda p: p.locator('input[type="email"]').first},
            {"name": "password_input", "locator": lambda p: p.locator('input[type="password"]').first},
            {"name": "sign_in_text", "locator": lambda p: p.get_by_text("Sign in", exact=False).first},
            {"name": "log_in_text", "locator": lambda p: p.get_by_text("Log in", exact=False).first},
        ],
    )
    return {
        "matched": bool(login_probe.get("matched")),
        "reason": "selector_login_pattern" if login_probe.get("matched") else "not_detected",
        "final_url": final_url,
        "attempts": login_probe.get("attempts", []),
    }


def _page_readiness_probe(page: Any, *, timeout_ms: int) -> dict[str, Any]:
    wait_started = time.monotonic()
    deadline = wait_started + max(timeout_ms, 1000) / 1000
    poll_s = 0.25

    loading_ui_selector = ".loading, .spinner, [data-testid*='loading'], [aria-busy='true']"
    product_anchor_probe = {
        "name": "product_anchor",
        "matched": False,
        "selected_strategy": None,
        "attempts": [],
    }
    network_idle = False
    loading_text_present = True
    loading_ui_present = True
    auth = {"matched": False, "reason": "not_detected", "final_url": "", "attempts": []}

    try:
        page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 4000))
        network_idle = True
    except Exception:
        network_idle = False

    while time.monotonic() < deadline:
        auth = _auth_probe(page)
        if auth.get("matched"):
            break

        try:
            body_text = (page.locator("body").inner_text(timeout=1000) or "").lower()
        except Exception:
            body_text = ""
        loading_text_present = "loading..." in body_text or body_text.strip() == "loading"

        try:
            loading_ui_present = _safe_count(page.locator(loading_ui_selector)) > 0
        except Exception:
            loading_ui_present = True

        product_anchor_probe = _selector_probe(
            page,
            "product_page_anchor",
            [
                {"name": "publishing_settings", "locator": lambda p: p.get_by_text("Publishing settings", exact=False).first},
                {"name": "personalization", "locator": lambda p: p.locator("text=/Personalization/i").first},
                {"name": "pricing", "locator": lambda p: p.locator("text=/Pricing/i").first},
                {"name": "shipping", "locator": lambda p: p.locator("text=/Shipping/i").first},
                {"name": "mockups_or_views", "locator": lambda p: p.locator("text=/Mockups|Views/i").first},
            ],
        )
        if product_anchor_probe.get("matched"):
            break

        page.wait_for_timeout(int(poll_s * 1000))

    waited_ms = int((time.monotonic() - wait_started) * 1000)
    final_url = str(page.url or "")
    ready = bool(product_anchor_probe.get("matched")) and not auth.get("matched")

    return {
        "final_url": final_url,
        "network_idle_reached": network_idle,
        "loading_text_present": loading_text_present,
        "loading_ui_present": loading_ui_present,
        "auth_redirect_detected": bool(auth.get("matched")),
        "auth_detection_reason": auth.get("reason"),
        "auth_attempts": auth.get("attempts", []),
        "first_anchor_match": product_anchor_probe.get("selected_strategy"),
        "anchor_probe_attempts": product_anchor_probe.get("attempts", []),
        "ready_for_probing": ready,
        "waited_ms": waited_ms,
        "timed_out": waited_ms >= timeout_ms and not ready and not auth.get("matched"),
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


def _resolve_channel(channel: str) -> str | None:
    val = (channel or "").strip()
    return val or None


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
    targets: list[AutomationTarget] = []
    if not args.bootstrap_login:
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

    if args.bootstrap_login:
        mode = "bootstrap_login"
    elif args.dry_run and args.screenshot_only:
        mode = "dry_run_screenshot_only"
    elif args.dry_run:
        mode = "dry_run"
    else:
        mode = "live"

    page = context = browser = playwright = None
    if args.bootstrap_login or not args.plan_only:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("Playwright is required. Install with `pip install playwright` and `playwright install chromium`.") from exc

        playwright = sync_playwright().start()
        channel = _resolve_channel(args.channel)
        if args.user_data_dir:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=args.user_data_dir,
                headless=False if args.bootstrap_login else args.headless,
                channel=channel,
            )
            page = context.pages[0] if context.pages else context.new_page()
        else:
            browser = playwright.chromium.launch(headless=args.headless, channel=channel)
            context_kwargs: dict[str, Any] = {}
            if args.storage_state and Path(args.storage_state).exists():
                context_kwargs["storage_state"] = args.storage_state
            context = browser.new_context(**context_kwargs)
            page = context.new_page()

        if args.bootstrap_login:
            if not args.user_data_dir:
                raise ValueError("--bootstrap-login requires --user-data-dir so the login session can persist.")
            page.goto("https://printify.com/app/login", wait_until="domcontentloaded", timeout=args.timeout_ms)
            _wait_for_enter(
                "Complete Printify/Google login in the opened browser window. Press Enter here when login is complete..."
            )
            shot = shots_root / f"{run_id}_bootstrap_login.png"
            page.screenshot(path=str(shot), full_page=True)
            report_rows.append(
                {
                    "id": "bootstrap_login",
                    "listing_slug": "bootstrap_login",
                    "printify_product_id": "",
                    "mode": mode,
                    "started_at": now_iso(),
                    "finished_at": now_iso(),
                    "ui_automation_status": "completed",
                    "ui_automation_last_result": "bootstrap_login_complete",
                    "ui_automation_screenshot_paths": [str(shot)],
                    "selector_diagnostics": {},
                    "readiness_diagnostics": {},
                    "action_log": [
                        {
                            "ts": now_iso(),
                            "step": "bootstrap_login",
                            "detail": {
                                "channel": channel,
                                "user_data_dir": args.user_data_dir,
                                "login_url": "https://printify.com/app/login",
                            },
                        }
                    ],
                }
            )

    try:
        for t in targets[: args.limit or len(targets)]:
            started = now_iso()
            action_log: list[dict[str, Any]] = []
            screenshot_paths: list[str] = []
            selector_diagnostics: dict[str, Any] = {}
            readiness_diagnostics: dict[str, Any] = {}
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

                    readiness_diagnostics = _page_readiness_probe(page, timeout_ms=args.readiness_timeout_ms)
                    selector_diagnostics["readiness"] = readiness_diagnostics
                    action_log.append({"ts": now_iso(), "step": "readiness_probe", "detail": readiness_diagnostics})

                    if args.pause_after_open and not args.headless:
                        _wait_for_enter(
                            f"Paused after open for {t.listing_slug}. URL={readiness_diagnostics.get('final_url')}. Press Enter to continue..."
                        )

                    if readiness_diagnostics.get("auth_redirect_detected"):
                        status = "auth_required"
                        result = "auth_required"
                        diag = (
                            f"{'redirected_to_login' if readiness_diagnostics.get('final_url') else 'auth_required'}; "
                            f"{AUTH_HELP_MESSAGE}"
                        )
                        action_log.append({"ts": now_iso(), "step": "auth_required", "detail": readiness_diagnostics})
                        action_log.append({"ts": now_iso(), "step": "auth_help", "detail": AUTH_HELP_MESSAGE})
                        print(AUTH_HELP_MESSAGE)
                        raise RuntimeError("auth_required")

                    if not readiness_diagnostics.get("ready_for_probing"):
                        status = "failed"
                        result = "page_not_ready"
                        diag = "page_still_loading_or_missing_anchor"
                        action_log.append({"ts": now_iso(), "step": "page_not_ready", "detail": readiness_diagnostics})
                        raise RuntimeError("page_not_ready")

                    personalization_toggle_probe = _personalization_toggle_probe(page)
                    publish_area_probe = _publish_area_probe(page)
                    selector_diagnostics["personalization_toggle"] = {
                        "matched": personalization_toggle_probe["matched"],
                        "selected_strategy": personalization_toggle_probe["selected_strategy"],
                        "attempts": personalization_toggle_probe["attempts"],
                    }
                    selector_diagnostics["publish_area"] = {
                        "matched": publish_area_probe["matched"],
                        "selected_strategy": publish_area_probe["selected_strategy"],
                        "attempts": publish_area_probe["attempts"],
                    }
                    action_log.append(
                        {
                            "ts": now_iso(),
                            "step": "selector_probe",
                            "detail": {
                                "personalization_toggle": selector_diagnostics["personalization_toggle"],
                                "publish_area": selector_diagnostics["publish_area"],
                            },
                        }
                    )

                    personalization_toggle = personalization_toggle_probe.get("locator")
                    has_toggle = bool(personalization_toggle_probe.get("matched"))

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
                            in_stock_probe = _variant_visibility_probe(page)
                            selector_diagnostics["variant_visibility_in_stock_only"] = {
                                "matched": in_stock_probe["matched"],
                                "selected_strategy": in_stock_probe["selected_strategy"],
                                "attempts": in_stock_probe["attempts"],
                            }
                            action_log.append({"ts": now_iso(), "step": "variant_visibility_probe", "detail": selector_diagnostics["variant_visibility_in_stock_only"]})
                            in_stock_option = in_stock_probe.get("locator")
                            if in_stock_probe.get("matched") and in_stock_option is not None:
                                in_stock_option.click(timeout=2000)
                                action_log.append({"ts": now_iso(), "step": "variant_visibility_set", "detail": "in_stock_only_clicked"})

                    for detail in t.sync_details_recommended:
                        label = SYNC_DETAIL_LABELS.get(detail, detail)
                        detail_probe = _sync_detail_probe(page, label)
                        selector_key = f"sync_detail::{detail}"
                        selector_diagnostics[selector_key] = {
                            "matched": detail_probe["matched"],
                            "selected_strategy": detail_probe["selected_strategy"],
                            "attempts": detail_probe["attempts"],
                        }
                        box = detail_probe.get("locator")
                        found = bool(detail_probe.get("matched"))
                        action_log.append(
                            {
                                "ts": now_iso(),
                                "step": "sync_detail_probe",
                                "detail": {
                                    "detail": detail,
                                    "label": label,
                                    "found": found,
                                    "selected_strategy": detail_probe["selected_strategy"],
                                    "attempts": detail_probe["attempts"],
                                },
                            }
                        )
                        if found and not args.screenshot_only:
                            try:
                                box.click(timeout=2000)
                                action_log.append({"ts": now_iso(), "step": "sync_detail_checked", "detail": detail})
                            except Exception:
                                action_log.append({"ts": now_iso(), "step": "sync_detail_check_failed", "detail": detail})

                    if args.confirm_each and not args.headless:
                        _wait_for_enter(f"Review product {t.listing_slug} in browser; press Enter to continue...")

                    if not args.dry_run and not args.screenshot_only:
                        publish_btn_probe = _publish_button_probe(page)
                        selector_diagnostics["publish_button"] = {
                            "matched": publish_btn_probe["matched"],
                            "selected_strategy": publish_btn_probe["selected_strategy"],
                            "attempts": publish_btn_probe["attempts"],
                        }
                        action_log.append({"ts": now_iso(), "step": "publish_button_probe", "detail": selector_diagnostics["publish_button"]})
                        publish_btn = publish_btn_probe.get("locator")
                        if publish_btn is None:
                            raise RuntimeError("Publish/Republish button not found")
                        publish_btn.click(timeout=args.timeout_ms)
                        action_log.append({"ts": now_iso(), "step": "publish_clicked", "detail": "publish_or_republish"})

                    after = shots_root / f"{run_id}_{t.listing_slug}_after.png"
                    page.screenshot(path=str(after), full_page=True)
                    screenshot_paths.append(str(after))
                    status = "completed"
                    result = "dry_run_complete" if args.dry_run else "live_complete"

            except SelectorNotFoundError as exc:
                status = "failed"
                result = "selector_no_match"
                diag = str(exc)
                selector_diagnostics[exc.key] = {"matched": False, "selected_strategy": None, "attempts": exc.attempts}
                action_log.append({"ts": now_iso(), "step": "selector_no_match", "detail": {"selector": exc.key, "attempts": exc.attempts}})

            except Exception as exc:
                if str(exc) not in {"auth_required", "page_not_ready"}:
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
                "selector_diagnostics": selector_diagnostics,
                "readiness_diagnostics": readiness_diagnostics or selector_diagnostics.get("readiness", {}),
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
    p.add_argument("--channel", default="", help="Optional branded browser channel, e.g. chrome or msedge")
    p.add_argument("--user-data-dir", default="", help="Launch persistent context with this browser profile directory")
    p.add_argument("--bootstrap-login", action="store_true", help="Open Printify login and pause for manual Google sign-in")
    p.add_argument("--timeout-ms", type=int, default=15000)
    p.add_argument("--readiness-timeout-ms", type=int, default=30000)
    p.add_argument("--pause-after-open", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()

    result = run_ui_automation(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
