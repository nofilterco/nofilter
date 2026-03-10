from __future__ import annotations

PRINTIFY_PUBLISH_STATUSES = {
    "NOT_ATTEMPTED",
    "PUBLISHED_TO_PRINTIFY",
    "PUBLISH_FAILED",
    "BLOCKED_PROFILE",
}

QUEUE_STATUSES = {
    "DRAFT",
    "READY_FOR_REVIEW",
    "APPROVED",
    "REJECTED",
    "BLOCKED_PROFILE",
    "PUBLISHED_TO_PRINTIFY",
    "SYNC_PENDING",
    "SYNCED_TO_SHOPIFY",
    "MANUAL_PERSONALIZATION_REQUIRED",
    "PUBLISH_FAILED",
    "SYNC_FAILED",
}

# Canonical launch_status lifecycle used across queue + publish + dashboard actions.
LAUNCH_STATUS_FLOW = [
    "READY_FOR_REVIEW",
    "APPROVED",
    "PUBLISHED_TO_PRINTIFY",
    "SYNC_PENDING",
    "SYNCED_TO_SHOPIFY",
    "MANUAL_PERSONALIZATION_REQUIRED",
    "BLOCKED_PROFILE",
    "PUBLISH_FAILED",
    "SYNC_FAILED",
]

SHOPIFY_SYNC_STATUSES = {
    "NOT_ATTEMPTED",
    "SYNC_PENDING",
    "SYNCED_TO_SHOPIFY",
    "SYNC_FAILED",
    "BLOCKED_PROFILE",
}


def normalize_publish_status(raw: str) -> str:
    token = (raw or "").strip().lower()
    if token in {"published_to_printify", "published", "created"}:
        return "PUBLISHED_TO_PRINTIFY"
    if token in {"publish_failed", "printify_api_error", "publish_error", "create_missing_id"}:
        return "PUBLISH_FAILED"
    if token in {"blocked_profile", "blocked_profile_unresolved"}:
        return "BLOCKED_PROFILE"
    return "NOT_ATTEMPTED"


def normalize_sync_status(raw: str) -> str:
    token = (raw or "").strip().lower()
    if token in {"not_attempted", ""}:
        return "NOT_ATTEMPTED"
    if token in {"synced_to_shopify", "synced"}:
        return "SYNCED_TO_SHOPIFY"
    if token in {"sync_pending", "printify_published", "printify_created", "not_checked"}:
        return "SYNC_PENDING"
    if token in {"sync_failed"}:
        return "SYNC_FAILED"
    if token in {"blocked_profile", "blocked_profile_unresolved"}:
        return "BLOCKED_PROFILE"
    return "NOT_ATTEMPTED"


def derive_launch_status(*, blocked: bool, publish_status: str, sync_status: str, needs_manual_setup: bool) -> str:
    if blocked:
        return "BLOCKED_PROFILE"
    if publish_status == "PUBLISH_FAILED":
        return "PUBLISH_FAILED"
    if sync_status == "SYNC_FAILED":
        return "SYNC_FAILED"
    if sync_status == "SYNCED_TO_SHOPIFY":
        return "SYNCED_TO_SHOPIFY"
    if sync_status == "SYNC_PENDING":
        return "SYNC_PENDING"
    if publish_status == "PUBLISHED_TO_PRINTIFY":
        return "PUBLISHED_TO_PRINTIFY"
    if needs_manual_setup:
        return "MANUAL_PERSONALIZATION_REQUIRED"
    return "NOT_ATTEMPTED"
