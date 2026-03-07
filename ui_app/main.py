import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
import subprocess

from dotenv import load_dotenv
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from drops import get_drop_names
from run_queue import generate_batch, load_queue, process_one, save_queue, seed_queue, verify_generated

STATE_PATH = ROOT / "ui_app" / "state.json"
QUEUE_PATH = ROOT / "queue.csv"
OUT_DIRS = [ROOT / "out", ROOT / "output"]
for d in OUT_DIRS:
    d.mkdir(parents=True, exist_ok=True)

DEFAULT_QUEUE_HEADERS = [
    "id",
    "status",
    "product_type",
    "drop",
    "drop_title",
    "motif",
    "vibe",
    "tone",
    "palette_hint",
    "embroidery_style",
    "embroidery_focus",
    "micro_niche",
    "object_state",
    "era_situation",
    "texture_cue",
    "variation_modifier",
    "motif_family",
    "motif_frame",
    "motif_keywords",
    "center_weight",
    "silhouette_strength",
    "product_rules",
    "style",
    "include_text",
    "phrase",
    "niche",
    "tags",
    "placement",
    "risk_flag",
    "policy_status",
    "risk_reason",
    "prompt_debug",
    "prompt_hash",
    "resolved_style",
    "quality_status",
    "quality_reason",
    "quality_json",
    "pipeline_stage",
    "concept_risk",
    "concept_reasons",
    "error_stage",
    "error_message",
    "debug_trace",
    "started_at",
    "finished_at",
    "drop_seq",
    "local_path",
    "generated_at",
    "approved_at",
    "printify_product_id",
    "published_at",
    "r2_url",
    "mockup_r2_url",
    "printify_image_id",
    "art_direction",
    "layout_archetype",
    "type_treatment",
    "icon_treatment",
    "frame_treatment",
    "visual_energy",
    "hierarchy_score",
    "visual_balance_score",
    "typography_quality_score",
    "icon_quality_score",
    "plate_dependency",
    "commercial_style_reason",
]

PROCESSED_STATUSES = {
    "ERROR",
    "CANCELLED",
    "GENERATED",
    "APPROVED",
    "PUBLISHED",
    "REJECTED",
    "SOLD_OUT",
    "HOLD",
    "HOLD_QUALITY",
    "HOLD_ERROR",
}

app = FastAPI(title="NoFilter Local UI")
app.mount("/out", StaticFiles(directory=ROOT / "out"), name="out")
app.mount("/output", StaticFiles(directory=ROOT / "output"), name="output")
_state_lock = Lock()


class QueueStore:
    def __init__(self, path: Path):
        self.path = path

    def _headers_from_file(self) -> list[str]:
        if not self.path.exists():
            return list(DEFAULT_QUEUE_HEADERS)
        with self.path.open("r", encoding="utf-8", newline="") as f:
            first = f.readline().strip()
        if not first:
            return list(DEFAULT_QUEUE_HEADERS)
        return [h.strip() for h in first.split(",") if h.strip()]

    def ensure_file(self) -> None:
        if self.path.exists() and self.path.stat().st_size > 0:
            return
        self.write_rows([], headers=self._headers_from_file())

    def load(self) -> list[dict[str, str]]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            self.ensure_file()
            return []
        with self.path.open("r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    def write_rows(self, rows: list[dict[str, str]], headers: list[str] | None = None) -> None:
        fieldnames = headers or self._headers_from_file()
        with self.path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            if rows:
                w.writerows(rows)

    def clear_all(self) -> int:
        rows = self.load()
        count = len(rows)
        self.write_rows([], headers=self._headers_from_file())
        return count

    def clear_processed(self) -> tuple[int, int]:
        rows = self.load()
        kept = []
        removed = 0
        for r in rows:
            status = (r.get("status", "") or "").strip().upper()
            if status in PROCESSED_STATUSES:
                removed += 1
                continue
            kept.append(r)
        self.write_rows(kept, headers=self._headers_from_file())
        return removed, len(kept)


store = QueueStore(QUEUE_PATH)


def get_version() -> str:
    try:
        return Path("VERSION").read_text(encoding="utf-8").strip()
    except Exception:
        return "dev"


def get_git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip()
    except Exception:
        return "no-git"


def _default_state() -> dict[str, Any]:
    return {
        "action": "idle",
        "detail": "",
        "updated_at": "",
        "is_running": False,
        "current_action": "",
        "current_row": "",
        "stop_requested": False,
        "cancel_pending": False,
        "history": [],
    }


def get_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return _default_state()
    data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    base = _default_state()
    base.update(data)
    return base


def add_history(action: str, outcome: str, message: str = "", row_id: str = "", stage: str = "") -> None:
    with _state_lock:
        payload = get_state()
        history = payload.get("history") or []
        history.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": action,
                "row_id": row_id,
                "stage": stage,
                "outcome": outcome,
                "message": message,
            }
        )
        payload["history"] = history[-50:]
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def set_state(action: str, detail: str = "", *, running: bool = False, current_action: str = "", current_row: str = "") -> None:
    with _state_lock:
        payload = get_state()
        payload.update(
            {
                "action": action,
                "detail": detail,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "is_running": running,
                "current_action": current_action,
                "current_row": current_row,
            }
        )
        if running:
            payload["stop_requested"] = False
            payload["cancel_pending"] = False
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def env_check() -> dict[str, Any]:
    def missing(keys: list[str]) -> list[str]:
        return [k for k in keys if not (os.getenv(k) or "").strip()]

    required_generate = ["OPENAI_API_KEY"]
    required_publish = [
        "PRINTIFY_TOKEN",
        "PRINTIFY_SHOP_ID",
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET",
        "R2_PUBLIC_BASE_URL",
    ]

    missing_generate = missing(required_generate)
    missing_publish = missing(required_publish)
    queue_rows = store.load()

    return {
        "queue_exists": QUEUE_PATH.exists(),
        "queue_rows": len(queue_rows),
        "drop_count": len(get_drop_names()),
        "required_for_generate": required_generate,
        "required_for_publish": required_publish,
        "missing_for_generate": missing_generate,
        "missing_for_publish": missing_publish,
        "ready_generate": not missing_generate,
        "ready_publish": not (missing_generate or missing_publish),
    }


@app.on_event("startup")
def on_startup() -> None:
    store.ensure_file()
    set_state("idle", "ui ready")


@app.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    template = (ROOT / "ui_app" / "templates" / "index.html").read_text(encoding="utf-8")
    html = template.replace("{{ version }}", get_version()).replace("{{ commit }}", get_git_commit())
    return HTMLResponse(html)


@app.get("/api/drops")
def api_drops() -> list[str]:
    return get_drop_names()


@app.get("/api/queue")
def api_queue() -> list[dict[str, str]]:
    return store.load()


@app.get("/api/gallery")
def api_gallery() -> list[str]:
    images: list[str] = []
    for folder in OUT_DIRS:
        if not folder.exists():
            continue
        for p in sorted(folder.glob("*.png"), reverse=True)[:40]:
            images.append(str(p.relative_to(ROOT)).replace("\\", "/"))
    return images[:80]


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    return get_state()


@app.get("/api/summary")
def api_summary() -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in store.load():
        key = (r.get("status", "") or "").strip().upper() or "UNKNOWN"
        counts[key] = counts.get(key, 0) + 1
    return counts


@app.get("/api/wizard")
def api_wizard() -> dict[str, Any]:
    return env_check()


@app.post("/actions/seed")
def action_seed(count: int = Form(...), drops_csv: str = Form(""), custom_drop: str = Form("")) -> JSONResponse:
    set_state("seeding", f"count={count}", running=True, current_action="seed")
    store.ensure_file()
    rows = load_queue()
    selected = [d.strip() for d in drops_csv.split(",") if d.strip()]
    if not selected and custom_drop.strip():
        selected = [custom_drop.strip()]
    if not selected:
        selected = get_drop_names()[:1]

    per_drop = max(1, count // max(1, len(selected)))
    remaining = count
    for drop in selected:
        n = min(per_drop, remaining)
        rows = seed_queue(rows, n, drop=drop)
        remaining -= n
    while remaining > 0:
        rows = seed_queue(rows, 1, drop=selected[0])
        remaining -= 1

    save_queue(rows)
    set_state("idle", "seed complete", running=False)
    add_history("seed", "ok", f"seeded={count}", stage="SEEDED")
    return JSONResponse({"ok": True, "seeded": count, "drops": selected, "queue_rows": len(rows)})


@app.post("/actions/generate")
def action_generate(count: int = Form(...)) -> JSONResponse:
    set_state("generating", f"count={count}", running=True, current_action="generate")
    generated, failed = generate_batch(count)
    set_state("idle", f"generated={generated},failed={failed}", running=False)
    add_history("generate", "ok", f"generated={generated},failed={failed}", stage="GENERATE_BATCH")
    return JSONResponse({"ok": True, "generated": generated, "failed": failed})


@app.post("/actions/verify")
def action_verify() -> JSONResponse:
    set_state("verifying", running=True, current_action="verify")
    checked, approved, rejected = verify_generated()
    set_state("idle", f"checked={checked},approved={approved},rejected={rejected}", running=False)
    add_history("verify", "ok", f"checked={checked},approved={approved},rejected={rejected}", stage="VERIFY")
    return JSONResponse({"ok": True, "checked": checked, "approved": approved, "rejected": rejected})


@app.post("/actions/publish")
def action_publish() -> JSONResponse:
    set_state("publishing", "once", running=True, current_action="publish")
    did = process_one(auto_seed=False)
    set_state("idle", f"published={int(bool(did))}", running=False)
    add_history("publish", "ok" if did else "noop", f"published={int(bool(did))}", stage="PUBLISH")
    return JSONResponse({"ok": True, "published": int(bool(did))})


@app.post("/actions/run_all")
def action_run_all() -> JSONResponse:
    set_state("publishing", "run_all", running=True, current_action="run_all")
    published = 0
    while True:
        if get_state().get("stop_requested"):
            break
        did = process_one(auto_seed=False)
        if not did:
            break
        published += 1
    set_state("idle", f"published={published}", running=False)
    add_history("run_all", "ok", f"published={published}", stage="PUBLISH")
    return JSONResponse({"ok": True, "published": published})


@app.post("/actions/clear_queue")
def action_clear_queue() -> JSONResponse:
    set_state("queue", "clearing all rows", running=True, current_action="clear_queue")
    removed = store.clear_all()
    set_state("idle", f"queue_cleared={removed}", running=False)
    add_history("clear_queue", "ok", f"removed={removed}", stage="QUEUE")
    return JSONResponse({"ok": True, "removed": removed, "message": "Queue cleared; headers preserved."})


@app.post("/actions/clear_processed")
def action_clear_processed() -> JSONResponse:
    set_state("queue", "clearing processed rows", running=True, current_action="clear_processed")
    removed, kept = store.clear_processed()
    set_state("idle", f"processed_removed={removed},kept={kept}", running=False)
    add_history("clear_processed", "ok", f"removed={removed},kept={kept}", stage="QUEUE")
    return JSONResponse({"ok": True, "removed": removed, "remaining": kept})


@app.post("/actions/stop")
def action_stop() -> JSONResponse:
    payload = get_state()
    payload["stop_requested"] = True
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    add_history("stop", "requested", "stop current run after current item")
    return JSONResponse({"ok": True, "stop_requested": True})


@app.post("/actions/cancel_pending")
def action_cancel_pending() -> JSONResponse:
    payload = get_state()
    payload["cancel_pending"] = True
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    rows = store.load()
    cancelled = 0
    for r in rows:
        if (r.get("status", "") or "").strip().upper() == "NEW":
            r["status"] = "CANCELLED"
            r["pipeline_stage"] = "CANCELLED"
            r["finished_at"] = datetime.now(timezone.utc).isoformat()
            cancelled += 1
    save_queue(rows)
    add_history("cancel_pending", "ok", f"cancelled={cancelled}")
    return JSONResponse({"ok": True, "cancelled": cancelled})
