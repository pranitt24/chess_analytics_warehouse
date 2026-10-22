"""Shared configuration. All paths are relative to the repo root (the folder containing etl/).

Values can be overridden in the .env file at the repo root:
    DATABASE_URL=postgresql://postgres:YOURPASSWORD@localhost:5432/chess_dw
    STOCKFISH_PATH=C:\\tools\\stockfish\\stockfish.exe
    SAMPLE_SEED=42
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv optional
    load_dotenv = None

ROOT = Path(__file__).resolve().parent.parent
if load_dotenv:
    load_dotenv(ROOT / ".env")

RAW_DIR = Path(os.getenv("RAW_DIR", ROOT / "data" / "raw"))
PROCESSED_DIR = Path(os.getenv("PROCESSED_DIR", ROOT / "data" / "processed"))
STAGING_DIR = PROCESSED_DIR / "staging"
DOCS_DIR = ROOT / "docs"
DB_DIR = ROOT / "db"

DATABASE_URL = os.getenv("DATABASE_URL", "")
SEED = int(os.getenv("SAMPLE_SEED", "42"))

# Study window (inclusive)
START_MONTH = "2013-01"
END_MONTH = "2018-02"
