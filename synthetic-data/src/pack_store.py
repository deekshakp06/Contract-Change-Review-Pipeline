"""
Pack store + duplicate-pair check (I5, A3).

A pair is identified by a hash of the extracted clause content of both documents.
If the same pair is delivered again, the stored pack is returned and the pipeline
(and therefore the model) is not called. The store is a local SQLite file for now;
the same table moves to Postgres once Docker works (T8).
"""
import sys
import json
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paths import OUTPUTS_DIR
from extract_clauses import extract_clauses

DB_PATH = OUTPUTS_DIR / "pack_store.db"


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS packs (
            pair_hash       TEXT PRIMARY KEY,
            previous_file   TEXT,
            current_file    TEXT,
            prompt_version  TEXT,
            model           TEXT,
            created_at      TEXT,
            delivery_count  INTEGER NOT NULL DEFAULT 1,
            pack_json       TEXT NOT NULL
        )
    """)
    return conn


def compute_pair_hash(previous_path, current_path):
    """Hash of the extracted clause content of both documents, previous first.
    Content-based, so re-saving a file with identical text still counts as the
    same pair. (Hashing raw file bytes is a one-line change if Rajath prefers it.)"""
    payload = {
        "previous": extract_clauses(str(previous_path)),
        "current": extract_clauses(str(current_path)),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def process_pair(previous_path, current_path, pipeline=None, prompt_version=None, model=None):
    """Returns (pack, was_duplicate, pair_hash).

    - Known pair: returns the stored pack, increments delivery_count, calls nothing.
    - New pair: runs the pipeline and stores the pack with prompt version and model (O3, G9).
    - A pack containing API errors is returned but NOT stored, so a re-delivery
      reprocesses it instead of serving the broken result."""
    pair_hash = compute_pair_hash(previous_path, current_path)
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT pack_json FROM packs WHERE pair_hash = ?", (pair_hash,)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE packs SET delivery_count = delivery_count + 1 WHERE pair_hash = ?",
                (pair_hash,),
            )
            conn.commit()
            return json.loads(row[0]), True, pair_hash

        if pipeline is None:
            from classify_clauses import run_pipeline, PROMPT_VERSION, DEPLOYMENT_NAME
            pipeline = run_pipeline
            prompt_version = prompt_version or PROMPT_VERSION
            model = model or DEPLOYMENT_NAME

        pack = pipeline(str(previous_path), str(current_path))

        if any(item.get("risk_level") == "Error" for item in pack):
            return pack, False, pair_hash

        conn.execute(
            "INSERT INTO packs (pair_hash, previous_file, current_file, prompt_version, model, created_at, pack_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                pair_hash,
                Path(previous_path).name,
                Path(current_path).name,
                prompt_version,
                model,
                datetime.now(timezone.utc).isoformat(),
                json.dumps(pack),
            ),
        )
        conn.commit()
        return pack, False, pair_hash
    finally:
        conn.close()