import requests
import os

SHOP_URL = os.getenv("SHOPIFY_STORE_URL")
TOKEN = os.getenv("SHOPIFY_ADMIN_TOKEN")

def add_to_collection(product_id, collection_id):
    url = f"https://{SHOP_URL}/admin/api/2024-01/collects.json"
    headers = {
        "X-Shopify-Access-Token": TOKEN,
        "Content-Type": "application/json"
    }
    payload = {
        "collect": {
            "product_id": product_id,
            "collection_id": collection_id
        }
    }
    requests.post(url, headers=headers, json=payload)