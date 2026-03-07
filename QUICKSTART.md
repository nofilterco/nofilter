# NoFilterCo – Queue-Driven Hat Pipeline (Windows Git Bash friendly)

NoFilterCo generates embroidery-safe nostalgic hat art, verifies quality/safety, uploads to R2, then publishes products to Printify (which syncs to Shopify).

## 1) Setup

```bash
python -m venv .venv
# Windows Git Bash:
source .venv/Scripts/activate
# Windows CMD:
# .venv\Scripts\activate.bat
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
```

Create `.env` and set at minimum:

- `OPENAI_API_KEY` (required for **Generate**)
- `PRINTIFY_TOKEN` (required for **Publish**)
- `PRINTIFY_SHOP_ID` (required for **Publish**)
- `R2_ACCOUNT_ID` (required for **Publish**)
- `R2_ACCESS_KEY_ID` (required for **Publish**)
- `R2_SECRET_ACCESS_KEY` (required for **Publish**)
- `R2_BUCKET` (required for **Publish**)
- `R2_PUBLIC_BASE_URL` (required for **Publish**)

Use `.env.example` as the template.

## 2) CLI first (recommended)

### Seed
```bash
python run_queue.py --seed 6 --drop "Analog Era"
python run_queue.py --seed 3 --drop "Early Internet" --include_text
```

### Generate
```bash
python run_queue.py --generate_batch 6
```

### Verify
```bash
python run_queue.py --verify_generated
```

### Publish
```bash
python run_queue.py --once
# or
python run_queue.py --run_all
```

The CLI reports pass counts explicitly (`generated`, `failed`, `approved`, `rejected`, `published`).

## 3) Local Control Panel (FastAPI)

Start from the repo root:

```bash
python -m uvicorn ui_app.main:app --host 127.0.0.1 --port 8080 --reload
```

Open <http://127.0.0.1:8080>.

The local control panel includes:

- Main actions: **Seed**, **Generate**, **Verify**, **Publish Once**, **Run All**
- Queue utilities: **Clear Generated/Processed**, **Clear Queue** (with confirmation)
- First-run readiness checks aligned to runtime env vars
- Queue table viewer and gallery viewer (`out/`, `output/`)
- Live status and last-action results
- Drop picker with search + select all/clear all

## 4) Embroidery safety config

If `nofilter.yaml` has an `embroidery:` section, these keys are supported:

- `embroidery_width_in`
- `embroidery_height_in`
- `safe_width_in`
- `safe_height_in`
- `max_colors`
- `min_detail_in`
- `min_text_in`
- `allowed_thread_palette`

If missing, safe defaults are used automatically.

## 5) Notes

- Runtime files are ignored: `ui_app/state.json`, `ui_app/logs/`, `ui_app/backups/`, `out/`, `output/`, `queue.csv.lock`.
- Raster generation remains the default path. `GENERATE_MODE=svg` is intentionally gated and falls back to raster until fully wired.
