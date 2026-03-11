from status_model import derive_launch_status, normalize_publish_status, normalize_sync_status


def test_normalize_status_aliases():
    assert normalize_publish_status("published") == "PUBLISHED_TO_PRINTIFY"
    assert normalize_publish_status("printify_api_error") == "PUBLISH_FAILED"
    assert normalize_sync_status("synced") == "SYNCED_TO_SHOPIFY"
    assert normalize_sync_status("not_checked") == "SYNC_PENDING"


def test_derive_launch_status_ordering():
    assert derive_launch_status(blocked=True, publish_status="PUBLISHED_TO_PRINTIFY", sync_status="SYNCED_TO_SHOPIFY", needs_manual_setup=False) == "BLOCKED_PROFILE"
    assert derive_launch_status(blocked=False, publish_status="PUBLISH_FAILED", sync_status="NOT_ATTEMPTED", needs_manual_setup=False) == "PUBLISH_FAILED"
    assert derive_launch_status(blocked=False, publish_status="PUBLISHED_TO_PRINTIFY", sync_status="SYNC_PENDING", needs_manual_setup=True) == "SYNC_PENDING"
