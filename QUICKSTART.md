# Quickstart (Crafted Occasion)

## 1) Install
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) Configure env
Copy `.env.example` to `.env` and set Printify + optional R2 values.

## 3) Seed first 20 launch listings
```bash
python run_queue.py --seed-launch
```

Optional filters:
```bash
python run_queue.py --seed-launch --collection family-reunion
python run_queue.py --seed-launch --family hoodie
```

## 4) Build placeholder assets
```bash
python run_queue.py --build-assets
```

## 5) Review and approve
```bash
python run_queue.py --approve-all
# or reject
python run_queue.py --reject-all
```

## 6) Publish approved listings
```bash
python run_queue.py --publish-approved
```

## 7) Export launch report
```bash
python run_queue.py --export-report
```

## UI dashboard
```bash
python -m uvicorn ui_app.main:app --host 127.0.0.1 --port 8080 --reload
```
Open `http://127.0.0.1:8080`.
