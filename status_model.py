from __future__ import annotations

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
    "SYNC_PENDING",
    "SYNCED_TO_SHOPIFY",
    "SYNC_FAILED",
}


def normalize_sync_status(raw: str) -> str:
    token = (raw or "").strip().lower()
    if token in {"synced_to_shopify", "synced"}:
        return "SYNCED_TO_SHOPIFY"
    if token in {"sync_pending", "printify_published", "printify_created", "not_checked"}:
        return "SYNC_PENDING"
    if token in {"sync_failed", "blocked_profile"}:
        return "SYNC_FAILED"
    return "SYNC_PENDING"
