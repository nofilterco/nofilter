# Quickstart (Crafted Occasion)

## 1) Install
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) Configure env
Copy `.env.example` to `.env` and set Printify credentials (Shopify optional but recommended for sync checks).

## 3) Seed launch listings
```bash
python run_queue.py --seed-launch
```
Optional filters:
```bash
python run_queue.py --seed-launch --collection bridal-party
python run_queue.py --seed-launch --family mug
```

## 4) Build styled assets
```bash
python run_queue.py --build-assets
```
Assets are generated using template style metadata (`style_pack`, `art_strategy`, safe-area hints).

## 5) Review and approve queue rows
```bash
python run_queue.py --approve-all
# or reject
python run_queue.py --reject-all
```

## 6) Publish approved listings
```bash
python run_queue.py --publish-approved
```
Publish writes status metadata for Printify + Shopify sync checks.

## 7) Export report for QA
```bash
python run_queue.py --export-report
```
Validate title/SEO/tag quality, stock flags, and publish/sync fields before full rollout.

## UI dashboard
```bash
python -m uvicorn ui_app.main:app --host 127.0.0.1 --port 8080 --reload
```
Open `http://127.0.0.1:8080`.
