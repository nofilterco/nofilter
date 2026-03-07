import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

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
    "drop_seq",
    "local_path",
    "generated_at",
    "approved_at",
    "printify_product_id",
    "published_at",
    "r2_url",
    "mockup_r2_url",
    "printify_image_id",
]

PROCESSED_STATUSES = {
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
def dashboard() -> str:
    return """<!doctype html>
<html><head><meta charset='utf-8'><title>NoFilter UI</title>
<style>
body{font-family:Inter,system-ui,-apple-system,sans-serif;max-width:1280px;margin:20px auto;padding:0 12px;color:#111}
h1,h2,h3{margin:0 0 10px 0}
.grid{display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:14px;align-items:start}
.card{border:1px solid #ddd;border-radius:10px;padding:12px;background:#fff}
.actions{display:flex;flex-wrap:wrap;gap:8px}
button{padding:8px 12px;border-radius:8px;border:1px solid #bbb;background:#f7f7f7;cursor:pointer}
button.primary{background:#111;color:#fff;border-color:#111}
input,select{padding:7px;border:1px solid #bbb;border-radius:6px}
.small{font-size:12px;color:#555}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;background:#eee;font-size:12px;margin-right:6px}
.badge.ok{background:#e4f9e4;color:#136d13}
.badge.warn{background:#fff4d6;color:#7a5a00}
.table-wrap{max-height:360px;overflow:auto;border:1px solid #ddd;border-radius:8px}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{padding:6px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}
#drops{max-height:220px;overflow:auto;border:1px solid #eee;border-radius:8px;padding:8px}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px}
.gallery a{font-size:12px;word-break:break-all}
</style>
</head><body>
<h1>NoFilter Local Control Panel</h1>
<div class='small'>Pipeline: Seed → Generate → Verify → Publish Once / Run All</div>
<br>
<div class='grid'>
  <div class='card'>
    <h3>Main actions</h3>
    <div style='display:grid;gap:8px;margin-bottom:10px'>
      <label>Seed count <input id='seed_count' type='number' value='5' min='1'></label>
      <label>Generate count <input id='gen_count' type='number' value='3' min='1'></label>
      <input id='custom_drop' placeholder='Optional fallback drop'>
      <input id='drops_csv' placeholder='Selected drops auto-filled'>
    </div>
    <div class='actions'>
      <button class='primary' onclick='doAction("seed")'>Seed</button>
      <button class='primary' onclick='doAction("generate")'>Generate</button>
      <button onclick='doAction("verify")'>Verify</button>
      <button onclick='doAction("publish")'>Publish Once</button>
      <button onclick='doAction("run_all")'>Run All</button>
      <button onclick='confirmAndRun("clear_processed")'>Clear Generated/Processed</button>
      <button onclick='confirmAndRun("clear_queue")'>Clear Queue</button>
    </div>
    <p class='small'>Clear Queue removes all rows but keeps queue.csv headers intact.</p>
    <h3>Last action result</h3>
    <pre id='result' class='small'></pre>
  </div>

  <div class='card'>
    <h3>First-run readiness</h3>
    <div id='wizard'></div>
    <h3 style='margin-top:14px'>Live status</h3>
    <pre id='status' class='small'></pre>
  </div>

  <div class='card'>
    <h3>Drops selection</h3>
    <input id='search' placeholder='Search drops' oninput='renderDrops()'>
    <div class='actions' style='margin-top:8px'>
      <button onclick='allDrops(true)'>Select all</button>
      <button onclick='allDrops(false)'>Clear all</button>
    </div>
    <div id='drops'></div>
  </div>
</div>

<h2 style='margin-top:16px'>Queue viewer</h2>
<div class='table-wrap'><table id='queue_table'></table></div>

<h2 style='margin-top:16px'>Gallery viewer</h2>
<div id='gallery' class='gallery'></div>

<script>
let drops=[]; let selected=new Set();
let queueRows=[];

async function postForm(url, fields={}) {
  const body = new URLSearchParams(fields);
  const res = await fetch(url, {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body});
  return res.json();
}

function selectedDropsCSV(){ return [...selected].join(','); }

async function doAction(name){
  try{
    let payload = {};
    if(name==='seed') payload = {count:document.getElementById('seed_count').value, drops_csv:selectedDropsCSV(), custom_drop:document.getElementById('custom_drop').value};
    if(name==='generate') payload = {count:document.getElementById('gen_count').value};
    const data = await postForm('/actions/'+name, payload);
    document.getElementById('result').textContent = JSON.stringify(data, null, 2);
  }catch(err){
    document.getElementById('result').textContent = 'Action failed: '+err;
  }
  await load();
}

async function confirmAndRun(name){
  const ok = confirm(name==='clear_queue' ? 'Clear all queue rows? This cannot be undone.' : 'Remove generated/processed rows and keep NEW rows?');
  if(!ok) return;
  await doAction(name);
}

function renderWizard(w){
  const g = w.ready_generate ? "<span class='badge ok'>Generate ready</span>" : "<span class='badge warn'>Generate blocked</span>";
  const p = w.ready_publish ? "<span class='badge ok'>Publish ready</span>" : "<span class='badge warn'>Publish blocked</span>";
  const mg = (w.missing_for_generate||[]).join(', ') || 'None';
  const mp = (w.missing_for_publish||[]).join(', ') || 'None';
  document.getElementById('wizard').innerHTML = `${g}${p}<div class='small'>Queue rows: ${w.queue_rows} | Drops: ${w.drop_count}</div><div class='small'><b>Missing for generate:</b> ${mg}</div><div class='small'><b>Missing for publish:</b> ${mp}</div>`;
}

function renderQueue(rows){
  queueRows = rows || [];
  const el = document.getElementById('queue_table');
  if(queueRows.length===0){ el.innerHTML = '<tr><td class="small">queue.csv has headers but no rows.</td></tr>'; return; }
  const cols = ['id','status','drop','motif','local_path','r2_url','printify_product_id','published_at'];
  const head = '<tr>'+cols.map(c=>`<th>${c}</th>`).join('')+'</tr>';
  const body = queueRows.slice(0,150).map(r=>'<tr>'+cols.map(c=>`<td>${(r[c]||'').toString().slice(0,140)}</td>`).join('')+'</tr>').join('');
  el.innerHTML = head + body;
}

function renderDrops(){
  const s=(document.getElementById('search').value||'').toLowerCase();
  document.getElementById('drops').innerHTML = drops.filter(d=>d.toLowerCase().includes(s)).map(d=>{
    const ck=selected.has(d)?'checked':''; const v=encodeURIComponent(d);
    return `<label><input type='checkbox' data-drop='${v}' ${ck} onchange='toggleDrop(this)'> ${d}</label><br>`;
  }).join('');
  document.getElementById('drops_csv').value = selectedDropsCSV();
}

function toggleDrop(el){
  const d=decodeURIComponent(el.dataset.drop||'');
  if(el.checked) selected.add(d); else selected.delete(d);
  document.getElementById('drops_csv').value = selectedDropsCSV();
}

function allDrops(on){ selected=new Set(on?drops:[]); renderDrops(); }

async function load(){
  const [q,s,w,d,g] = await Promise.all([
    fetch('/api/queue').then(r=>r.json()),
    fetch('/api/status').then(r=>r.json()),
    fetch('/api/wizard').then(r=>r.json()),
    fetch('/api/drops').then(r=>r.json()),
    fetch('/api/gallery').then(r=>r.json()),
  ]);
  drops = d || [];
  if(selected.size===0) drops.forEach(x=>selected.add(x));
  renderDrops();
  renderQueue(q);
  renderWizard(w);
  document.getElementById('status').textContent = JSON.stringify(s, null, 2);
  document.getElementById('gallery').innerHTML = (g||[]).map(x=>`<div><a href='/${x}' target='_blank'>${x}</a></div>`).join('');
}

load();
setInterval(load, 4000);
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
    set_state("idle", "seed complete")
    return JSONResponse({"ok": True, "seeded": count, "drops": selected, "queue_rows": len(rows)})


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


@app.post("/actions/clear_queue")
def action_clear_queue() -> JSONResponse:
    set_state("queue", "clearing all rows")
    removed = store.clear_all()
    set_state("idle", f"queue_cleared={removed}")
    return JSONResponse({"ok": True, "removed": removed, "message": "Queue cleared; headers preserved."})


@app.post("/actions/clear_processed")
def action_clear_processed() -> JSONResponse:
    set_state("queue", "clearing processed rows")
    removed, kept = store.clear_processed()
    set_state("idle", f"processed_removed={removed},kept={kept}")
    return JSONResponse({"ok": True, "removed": removed, "remaining": kept})
