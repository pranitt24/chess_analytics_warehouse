# Run the dashboard (backend + UI)

Needs: `.env` with `DATABASE_URL` (database `chess_warehouse`), the warehouse loaded, `pip install -r requirements.txt`.

```powershell
# 1. API only (UI served from frontend\dist if it exists)
uvicorn backend.app.main:app --port 8000
# open http://localhost:8000  and  http://localhost:8000/docs
```

Build the UI once (needs Node.js; a teammate can also send you the finished `frontend\dist` folder):

```powershell
cd frontend; npm install; npm run build; cd ..
```

UI development without the database: `cd frontend; npm run mock` (serves `public\mock\*.json`).

Test the SQL layer against the real database (no FastAPI needed):
`python tests\test_backend_sql.py --user postgres --db chess_warehouse` (set `$env:PGPASSWORD` first; psql path via `--psql`).

## Where each page gets its data
| Page | Source |
|---|---|
| Overview, Schema, OLAP, Exploration, Cheat triage | PostgreSQL (`game_fact`, dims, `cheat_score`) |
| Clustering, Association rules | `data\processed\mining\cluster_profile_k*.csv`, `assoc_rules_*.csv` |
| Cheat classifier table, Tier 1 validation | `data\processed\cheat\classifier_results.csv`, `tier1_validation_pairs.csv` |
| Classification, Regression, Hierarchical, Apriori vs FP-Growth | `data\processed\api\mining_*.json` (scripts not yet run; the page says "Not computed yet") |
