import json
import os
from typing import Dict

COUNTS_PATH = os.getenv("DROP_COUNTS_PATH", "drop_counts.json")

def load_counts() -> Dict[str, int]:
    if not os.path.exists(COUNTS_PATH):
        return {}
    try:
        with open(COUNTS_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f) or {}
        return {str(k): int(v) for k, v in raw.items()}
    except Exception:
        return {}

def save_counts(counts: Dict[str, int]) -> None:
    with open(COUNTS_PATH, "w", encoding="utf-8") as f:
        json.dump({k: int(v) for k, v in counts.items()}, f, indent=2)

def can_publish(drop_slug: str, limit: int) -> bool:
    if not drop_slug or limit <= 0:
        return True
    counts = load_counts()
    return int(counts.get(drop_slug, 0)) < int(limit)

def increment(drop_slug: str) -> int:
    if not drop_slug:
        return 0
    counts = load_counts()
    counts[drop_slug] = int(counts.get(drop_slug, 0)) + 1
    save_counts(counts)
    return counts[drop_slug]
