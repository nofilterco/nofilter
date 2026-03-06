import os
from typing import Any, Dict, List, Optional
import yaml


def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    out: List[str] = []
    last_dash = False
    for ch in s:
        if ch.isalnum():
            out.append(ch)
            last_dash = False
        else:
            if not last_dash:
                out.append("-")
                last_dash = True
    return "".join(out).strip("-")[:80]


def _drops_path() -> str:
    # drops.yaml sits in the repo root, next to this file
    return os.path.join(os.path.dirname(__file__), "drops.yaml")


def load_config() -> Dict[str, Any]:
    path = _drops_path()
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing drops.yaml at {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("drops.yaml must be a YAML mapping (dict) at the top level")
    return data


def _iter_drop_entries(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Normalizes drop entries into a list of dicts.

    Supports:
      A) New v2 list form:
         drops:
           - name: "Analog Era"
             slug: "analog-era"
             motifs: [...]
      B) Legacy list form:
         drops:
           - name: "analog-era"
             title: "Analog Era"
             motifs: [...]
      C) Legacy mapping form:
         analog-era: { title: "Analog Era", motifs: [...], limited: 500 }
    """
    out: List[Dict[str, Any]] = []

    # C) mapping form (skip known meta keys)
    for k, v in (cfg or {}).items():
        if k in {"drops", "safe_phrases", "palette_hints", "embroidery_styles", "collection", "version"}:
            continue
        if isinstance(v, dict):
            e = dict(v)
            e.setdefault("slug", slugify(k))
            e.setdefault("name", e.get("title") or k)
            out.append(e)

    # A/B) list form under "drops"
    drops_list = cfg.get("drops")
    if isinstance(drops_list, list):
        for d in drops_list:
            if not isinstance(d, dict):
                continue
            e = dict(d)
            # accept slug OR derive from slugified name/title
            if not e.get("slug"):
                base = e.get("name") or e.get("title") or ""
                e["slug"] = slugify(str(base))
            # ensure display name exists
            if not e.get("name"):
                e["name"] = e.get("title") or e.get("slug") or ""
            out.append(e)

    # de-dupe by slug
    seen = set()
    uniq: List[Dict[str, Any]] = []
    for e in out:
        sl = e.get("slug") or slugify(str(e.get("name") or ""))
        if not sl or sl in seen:
            continue
        seen.add(sl)
        e["slug"] = sl
        uniq.append(e)
    return uniq


def get_drop_names() -> List[str]:
    """Return drop slugs (stable identifiers)."""
    cfg = load_config()
    return [d.get("slug") for d in _iter_drop_entries(cfg) if d.get("slug")]


def get_drop(name_or_slug: str) -> Optional[Dict[str, Any]]:
    if not name_or_slug:
        return None
    cfg = load_config()
    want = slugify(name_or_slug)
    for d in _iter_drop_entries(cfg):
        if (d.get("slug") or "") == want:
            return d
        if slugify(str(d.get("name") or "")) == want:
            return d
        if slugify(str(d.get("title") or "")) == want:
            return d
    # mapping direct key fallback
    if isinstance(cfg.get(name_or_slug), dict):
        e = dict(cfg[name_or_slug])
        e.setdefault("slug", slugify(name_or_slug))
        e.setdefault("name", e.get("title") or name_or_slug)
        return e
    return None


def get_drop_title(name_or_slug: str) -> str:
    """Human-facing name for titles/descriptions."""
    d = get_drop(name_or_slug) or {}
    # prefer explicit name/title
    title = d.get("name") or d.get("title") or ""
    if title:
        return str(title)
    # fall back to slug -> Title Case
    sl = d.get("slug") or slugify(name_or_slug)
    return " ".join([w.capitalize() for w in (sl or "").split("-") if w]) or name_or_slug


def get_drop_motifs(name_or_slug: str) -> List[str]:
    d = get_drop(name_or_slug) or {}
    motifs = d.get("motifs") or []
    if isinstance(motifs, list):
        return [str(x) for x in motifs if str(x).strip()]
    return []


def get_drop_limited(name_or_slug: str, default: Optional[int] = None) -> int:
    if default is None:
        try:
            default = int(os.getenv("LIMITED_RUN_DEFAULT", "500"))
        except Exception:
            default = 500
    d = get_drop(name_or_slug) or {}
    val = d.get("limited")
    try:
        return int(val) if val is not None else int(default)
    except Exception:
        return int(default)


def get_drop_vibe(name_or_slug: str) -> str:
    d = get_drop(name_or_slug) or {}
    return str(d.get("vibe") or "").strip()


def get_drop_embroidery_focus(name_or_slug: str) -> str:
    d = get_drop(name_or_slug) or {}
    return str(d.get("embroidery_focus") or "").strip()


def build_drop_tags(name_or_slug: str) -> List[str]:
    if not name_or_slug:
        return []
    d = get_drop(name_or_slug) or {}
    slug = d.get("slug") or slugify(name_or_slug)

    tags = [
        f"drop:{slug}",
        f"collection:{slug}",
        f"collection-handle:{slug}",
    ]
    # scarcity tag
    limited = get_drop_limited(slug)
    if limited:
        tags.append(f"limited:{int(limited)}")
    return tags


def get_safe_phrases() -> List[str]:
    cfg = load_config()
    items = cfg.get("safe_phrases") or []
    return [str(x) for x in items if str(x).strip()] if isinstance(items, list) else []


def get_palette_hints() -> List[str]:
    cfg = load_config()
    items = cfg.get("palette_hints") or []
    return [str(x) for x in items if str(x).strip()] if isinstance(items, list) else []


def get_embroidery_styles() -> List[str]:
    cfg = load_config()
    items = cfg.get("embroidery_styles") or []
    return [str(x) for x in items if str(x).strip()] if isinstance(items, list) else []


def pick_safe_phrase() -> str:
    import random
    phrases = get_safe_phrases()
    return random.choice(phrases) if phrases else ""


def pick_palette_hint() -> str:
    import random
    pals = get_palette_hints()
    return random.choice(pals) if pals else ""


def pick_embroidery_style() -> str:
    import random
    styles = get_embroidery_styles()
    return random.choice(styles) if styles else ""
