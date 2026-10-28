"""FastAPI backend for the Chess Analytics Warehouse dashboard.

Run from the repo root:   uvicorn backend.app.main:app --port 8000
Open http://localhost:8000  (the built UI in frontend/dist is served at /).
Read-only. No usernames are ever returned; games are identified by their Lichess link.
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, olap, queries, store
from .common import BANDS, CATEGORIES, BadParam

app = FastAPI(title="Chess Analytics Warehouse API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:3000"],
                   allow_methods=["GET"], allow_headers=["*"])


@app.exception_handler(BadParam)
async def _bad_param(_, e):
    return JSONResponse({"detail": str(e)}, status_code=400)


@app.exception_handler(db.MissingTable)
async def _missing(_, e):
    return JSONResponse({"available": False, "reason": f"Table not built yet ({e}). Run the matching pipeline script."})


@app.exception_handler(db.DbError)
async def _db_error(_, e):
    return JSONResponse({"detail": f"Database error: {e}"}, status_code=503)


def q(request: Request):
    return dict(request.query_params)


@app.get("/api/health")
def health():
    db.run("SELECT 1")
    return {"status": "ok"}


@app.get("/api/meta")
def meta():
    return {"years": list(range(2013, 2019)), "categories": CATEGORIES, "rating_bands": BANDS,
            "missing_months": queries.GAP_MONTHS}


@app.get("/api/overview")
def overview():
    return queries.overview()


@app.get("/api/schema")
def schema():
    return queries.schema()


@app.get("/api/olap/monthly")
def olap_monthly():
    return queries.monthly()


@app.get("/api/olap/{op}")
def olap_op(op: str, request: Request):
    if op not in olap.OPS:
        raise HTTPException(404, f"Unknown OLAP operation '{op}'. Use one of: {', '.join(olap.OPS)}")
    return olap.OPS[op](q(request))


@app.get("/api/explore/summary")
def explore_summary():
    return queries.explore_summary()


@app.get("/api/explore/boxplot")
def explore_boxplot(request: Request):
    return queries.explore_boxplot(q(request))


@app.get("/api/explore/histogram")
def explore_histogram(request: Request):
    return queries.explore_histogram(q(request))


@app.get("/api/explore/scatter")
def explore_scatter(request: Request):
    return queries.explore_scatter(q(request))


@app.get("/api/mining/clusters")
def mining_clusters():
    return store.clusters()


@app.get("/api/mining/rules")
def mining_rules(request: Request):
    return store.rules(q(request))


@app.get("/api/mining/classification")
def mining_classification():
    return store.api_json("mining_classification", "Run: python mining\\classification_regression.py")


@app.get("/api/mining/regression")
def mining_regression():
    return store.api_json("mining_regression", "Run: python mining\\classification_regression.py")


@app.get("/api/mining/hierarchical")
def mining_hierarchical():
    return store.api_json("mining_hierarchical", "Run: python mining\\hierarchical_and_apriori.py")


@app.get("/api/mining/apriori_benchmark")
def mining_apriori():
    return store.api_json("mining_apriori_benchmark", "Run: python mining\\hierarchical_and_apriori.py")


@app.get("/api/cheat/summary")
def cheat_summary():
    return queries.cheat_summary()


@app.get("/api/cheat/top")
def cheat_top(request: Request):
    return queries.cheat_top(q(request))


@app.get("/api/cheat/classifier")
def cheat_classifier():
    return store.classifier()


@app.get("/api/cheat/game")
def cheat_game(request: Request):
    r = queries.cheat_game(q(request))
    if r is None:
        raise HTTPException(404, "No analysis for this game (only about 51,000 games from 2017-2018 are scored).")
    return r


DIST = db.ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="ui")
else:
    @app.get("/")
    def root():
        return {"message": "API is running. Build the UI (cd frontend; npm install; npm run build) and restart "
                           "to serve it here, or open /docs for the API."}
