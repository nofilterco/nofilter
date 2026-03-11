import os

from shopify_helper import _base_url


def test_base_url_reads_env_dynamically(monkeypatch):
    monkeypatch.setenv("SHOPIFY_STORE_URL", "example.myshopify.com")
    assert _base_url() == "https://example.myshopify.com/admin/api/2024-01"
    monkeypatch.setenv("SHOPIFY_STORE_URL", "changed.myshopify.com")
    assert _base_url() == "https://changed.myshopify.com/admin/api/2024-01"
    monkeypatch.delenv("SHOPIFY_STORE_URL", raising=False)
    assert _base_url() == "https:///admin/api/2024-01"
