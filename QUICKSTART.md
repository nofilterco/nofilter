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

Create `.env` and set:

- `OPENAI_API_KEY`
- `PRINTIFY_TOKEN`
- `PRINTIFY_SHOP_ID`
- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY`
- `R2_SECRET_KEY`
- `R2_BUCKET`

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

The CLI now reports pass counts explicitly (`generated`, `failed`, `approved`, `rejected`, `published`).

## 3) Local control panel (FastAPI)

```bash
uvicorn ui_app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open <http://127.0.0.1:8000>.

Dashboard includes:
- Seed / Generate / Verify / Publish / Run All
- Queue viewer
- Gallery viewer (`out/`, `output/`)
- Live status panel
- First-run wizard (env + queue checks)
- Drop picker with search + select all/none + custom drop fallback

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
