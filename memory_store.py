import json
import os
from collections import deque
from typing import Dict, Deque, List

MEMORY_PATH = os.getenv("MEMORY_PATH", "recent_memory.json")
WINDOW = int(os.getenv("MEMORY_WINDOW", "50"))

KEYS = ["motif", "micro_niche", "era_situation", "style", "phrase"]

def load_memory() -> Dict[str, Deque[str]]:
    if not os.path.exists(MEMORY_PATH):
        return {k: deque(maxlen=WINDOW) for k in KEYS}
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f) or {}
    except Exception:
        raw = {}
    mem: Dict[str, Deque[str]] = {}
    for k in KEYS:
        mem[k] = deque([str(x) for x in (raw.get(k) or [])], maxlen=WINDOW)
    return mem

def save_memory(mem: Dict[str, Deque[str]]) -> None:
    out = {k: list(mem.get(k, [])) for k in KEYS}
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

def seen_recent(mem: Dict[str, Deque[str]], k: str, value: str) -> bool:
    value = (value or "").strip().lower()
    if not value:
        return False
    return value in (x.strip().lower() for x in mem.get(k, []))

def push(mem: Dict[str, Deque[str]], item: Dict[str, str]) -> None:
    for k in KEYS:
        v = (item.get(k) or "").strip()
        if v:
            mem[k].append(v)
