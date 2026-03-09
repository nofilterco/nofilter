from __future__ import annotations

import json
from pathlib import Path
import sys
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from catalog_config import load_catalog
from catalog_queue import dump_launch_report, dump_ops_review_csv, load_rows
from run_queue import build_assets_for_rows, export_row_json, mark_review, publish_approved, recheck_sync, seed_listings

app = FastAPI(title="Crafted Occasion Catalog Dashboard")
app.mount("/out", StaticFiles(directory=ROOT / "out"), name="out")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (ROOT / "ui_app" / "templates" / "index.html").read_text(encoding="utf-8")


@app.get("/api/queue")
def queue() -> JSONResponse:
    return JSONResponse(load_rows())


@app.get("/api/catalog")
def catalog() -> JSONResponse:
    return JSONResponse(load_catalog())


@app.post("/actions/seed")
def action_seed(collection: str = Form(""), family: str = Form("")) -> JSONResponse:
    return JSONResponse({"seeded": seed_listings(True, collection, family)})


@app.post("/actions/assets")
def action_assets() -> JSONResponse:
    return JSONResponse({"assets": build_assets_for_rows()})


@app.post("/actions/approve")
def action_approve(ids: str = Form("")) -> JSONResponse:
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    return JSONResponse({"approved": mark_review("APPROVED", id_list or None)})


@app.post("/actions/reject")
def action_reject(ids: str = Form("")) -> JSONResponse:
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    return JSONResponse({"rejected": mark_review("REJECTED", id_list or None)})


@app.post("/actions/publish")
def action_publish() -> JSONResponse:
    return JSONResponse({"published": publish_approved()})


@app.post("/actions/recheck-sync")
def action_recheck_sync(ids: str = Form("")) -> JSONResponse:
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    return JSONResponse({"sync_checked": recheck_sync(id_list or None)})


@app.post("/actions/export")
def action_export() -> JSONResponse:
    path = dump_launch_report("launch_report.json")
    ops = dump_ops_review_csv("launch_ops_review.csv")
    return JSONResponse({"report": path, "ops_csv": ops})


@app.post("/actions/export-row")
def action_export_row(id: str = Form(...)) -> JSONResponse:
    return JSONResponse({"row_json": export_row_json(id)})
