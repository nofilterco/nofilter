# NoFilterCo – 90s Nostalgia Hats (V1 → Blueprint-aligned)

This project generates **copyright-safe 90s nostalgia** hat designs (embroidery-friendly),
uploads them to **Cloudflare R2**, then creates + publishes **Printify** hat products
that auto-sync to **Shopify** (via your existing Printify → Shopify connection).

## 1) Setup

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
```

Create `.env` from `.env.example` and fill in values.

## 2) Seed your queue (adds NEW rows)

Seed 6 hats for the **Analog Era** drop (icon-only):

```bash
python run_queue.py --seed 6 --drop "Analog Era"
```

Seed 3 hats that include short safe text:

```bash
python run_queue.py --seed 3 --drop "Early Internet" --include_text
```

## 3) Publish hats

Publish one item:

```bash
python run_queue.py --once
```

Publish everything queued:

```bash
python run_queue.py --loop
```

Alias (same behavior):

```bash
python run_queue.py --run_all
```

## 4) Approvals gate (optional)

If a row is flagged as `risk_flag=REVIEW`, the runner will set `status=HOLD`.
To force it through, edit `queue.csv` and set `policy_status=APPROVED`.

(You should only do this if you've manually verified it's safe.)

## 5) Hat catalog selection

By default the runner tries to automatically find a hat blueprint/provider.

If you want to lock the exact hat product, set:

- `PRINTIFY_HAT_BLUEPRINT_ID`
- `PRINTIFY_HAT_PROVIDER_ID` (optional)
- `PRINTIFY_HAT_VARIANT_IDS` (optional; comma-separated)

## Notes on embroidery quality

The generator post-processes designs down to **<=6 colors** with thick shapes,
and exports a **transparent PNG** for Printify.
You can tune scale with `HAT_ART_SCALE` and colors with `HAT_COLORS`.


## V2: Drop Mode (curated hats)

- Seed 12 hats evenly across all drops:

```bash
python run_queue.py --seed 12 --drop_mode
```

- Seed only Drop 01 (Analog Era):

```bash
python run_queue.py --seed 6 --drop "Analog Era"
```

- Enable simple mockups (uploaded to R2) by setting `MAKE_MOCKUPS=1` in `.env`.

### Shopify Collections (recommended)

Each published product is tagged with:

- `drop:<slug>` (e.g. `drop:analog-era`)
- `collection:<slug>`
- `collection-handle:<slug>`
- `limited:<count>` (e.g. `limited:500`)

Create Shopify automated collections using tag rules like `drop:analog-era`.
