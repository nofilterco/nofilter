import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from drops import get_drop_names
from run_queue import generate_batch, load_queue, process_one, save_queue, seed_queue, verify_generated

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "ui_app" / "state.json"
QUEUE_PATH = ROOT / "queue.csv"
OUT_DIRS = [ROOT / "out", ROOT / "output"]
for d in OUT_DIRS:
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="NoFilter Local UI")
app.mount("/out", StaticFiles(directory=ROOT / "out"), name="out")
app.mount("/output", StaticFiles(directory=ROOT / "output"), name="output")
_state_lock = Lock()


class QueueStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[dict[str, str]]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    def save(self, rows: list[dict[str, str]]) -> None:
        if not rows:
            return
        fieldnames = list(rows[0].keys())
        with self.path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)


store = QueueStore(QUEUE_PATH)


def set_state(action: str, detail: str = "") -> None:
    payload = {
        "action": action,
        "detail": detail,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with _state_lock:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"action": "idle", "detail": "", "updated_at": ""}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def env_check() -> dict[str, Any]:
    required = [
        "OPENAI_API_KEY",
        "PRINTIFY_TOKEN",
        "PRINTIFY_SHOP_ID",
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_KEY",
        "R2_BUCKET",
    ]
    missing = [k for k in required if not (os.getenv(k) or "").strip()]
    return {
        "queue_exists": QUEUE_PATH.exists(),
        "missing_env": missing,
        "drop_count": len(get_drop_names()),
    }


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return """<!doctype html>
<html><head><meta charset='utf-8'><title>NoFilter UI</title>
<style>body{font-family:sans-serif;max-width:1100px;margin:20px auto}button{margin:4px;padding:8px} .cols{display:flex;gap:20px}.col{flex:1;border:1px solid #ddd;padding:12px;border-radius:8px} pre{background:#f7f7f7;padding:10px;max-height:300px;overflow:auto}</style>
</head><body>
<h1>NoFilter Local Control Panel</h1>
<div class='cols'>
<div class='col'><h3>Pipeline</h3>
<form method='post' action='/actions/seed'>
<label>Count <input type='number' name='count' value='3' min='1'></label><br>
<label>Custom drop fallback <input name='custom_drop'></label><br>
<label>Selected drops (comma-separated) <input name='drops_csv' placeholder='Analog Era,Early Internet' style='width:100%'></label><br>
<button type='submit'>Seed</button></form>
<form method='post' action='/actions/generate'><label>N <input type='number' name='count' value='3' min='1'></label><button type='submit'>Generate</button></form>
<form method='post' action='/actions/verify'><button type='submit'>Verify</button></form>
<form method='post' action='/actions/publish'><button type='submit'>Publish Once</button></form>
<form method='post' action='/actions/run_all'><button type='submit'>Run All</button></form>
</div>
<div class='col'><h3>First-run wizard</h3><div id='wizard'></div><h3>Live status</h3><div id='status'></div></div>
<div class='col'><h3>Drops</h3><input id='search' placeholder='search drops' oninput='renderDrops()'><br><button onclick='allDrops(true)'>All</button><button onclick='allDrops(false)'>None</button><div id='drops'></div></div>
</div>
<h3>Queue viewer</h3><pre id='queue'></pre>
<h3>Gallery viewer</h3><div id='gallery'></div>
<script>
let drops=[]; let selected=new Set();
async function load(){
 const [q,s,w,d,g]=await Promise.all([fetch('/api/queue').then(r=>r.json()),fetch('/api/status').then(r=>r.json()),fetch('/api/wizard').then(r=>r.json()),fetch('/api/drops').then(r=>r.json()),fetch('/api/gallery').then(r=>r.json())]);
 document.getElementById('queue').textContent=JSON.stringify(q.slice(0,30),null,2);
 document.getElementById('status').textContent=JSON.stringify(s,null,2);
 document.getElementById('wizard').textContent=JSON.stringify(w,null,2);
 drops=d; if(selected.size===0){drops.forEach(x=>selected.add(x));}
 renderDrops();
 document.getElementById('gallery').innerHTML=g.map(x=>`<a href='/${x}' target='_blank'>${x}</a>`).join('<br>');
}
function renderDrops(){const s=(document.getElementById('search').value||'').toLowerCase();document.getElementById('drops').innerHTML=drops.filter(d=>d.toLowerCase().includes(s)).map(d=>{const ck=selected.has(d)?'checked':'';const v=encodeURIComponent(d);return `<label><input type='checkbox' data-drop='${v}' ${ck} onchange='toggleDrop(this)'> ${d}</label><br>`}).join('');document.querySelector("input[name='drops_csv']").value=[...selected].join(',');}
function toggleDrop(el){const d=decodeURIComponent(el.dataset.drop||'');if(el.checked)selected.add(d); else selected.delete(d); document.querySelector("input[name='drops_csv']").value=[...selected].join(',');}
function allDrops(on){selected=new Set(on?drops:[]);renderDrops();}
load(); setInterval(load,4000);
</script>
</body></html>"""


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


@app.get("/api/wizard")
def api_wizard() -> dict[str, Any]:
    return env_check()


@app.post("/actions/seed")
def action_seed(count: int = Form(...), drops_csv: str = Form(""), custom_drop: str = Form("")) -> JSONResponse:
    set_state("seeding", f"count={count}")
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
    set_state("idle", "seed complete")
    return JSONResponse({"ok": True, "seeded": count, "drops": selected})


@app.post("/actions/generate")
def action_generate(count: int = Form(...)) -> JSONResponse:
    set_state("generating", f"count={count}")
    generated, failed = generate_batch(count)
    set_state("idle", f"generated={generated},failed={failed}")
    return JSONResponse({"ok": True, "generated": generated, "failed": failed})


@app.post("/actions/verify")
def action_verify() -> JSONResponse:
    set_state("verifying")
    checked, approved, rejected = verify_generated()
    set_state("idle", f"checked={checked},approved={approved},rejected={rejected}")
    return JSONResponse({"ok": True, "checked": checked, "approved": approved, "rejected": rejected})


@app.post("/actions/publish")
def action_publish() -> JSONResponse:
    set_state("publishing", "once")
    did = process_one(auto_seed=False)
    set_state("idle", f"published={int(bool(did))}")
    return JSONResponse({"ok": True, "published": int(bool(did))})


@app.post("/actions/run_all")
def action_run_all() -> JSONResponse:
    set_state("publishing", "run_all")
    published = 0
    while True:
        did = process_one(auto_seed=False)
        if not did:
            break
        published += 1
    set_state("idle", f"published={published}")
    return JSONResponse({"ok": True, "published": published})
