"""
Reliable clause processing.

  R2  bounded concurrency      MAX_CONCURRENT_CALLS (setting, default 4)
  R3  retries, growing delay   MAX_RETRIES (default 3), RETRY_BASE_SECONDS (default 2) -> 2s, 4s, 8s
  R4  error queue              clauses that still fail are marked 'failed' (view: error_queue); the rest finish
  R5  resume                   re-delivering an unfinished pair reprocesses only the failed/pending clauses
  R6  cost ceiling             COST_CEILING_PER_DOCUMENT stops the run; the partial pack is kept and marked partial
  R8  crash recovery           every clause result is saved as it completes
  A3  duplicates               a pair whose complete pack is stored returns it with no model call
  C3  only clauses whose TEXT changed go to the model (edited, added, removed, or moved and edited)

Cost settings (all in .env or the environment; nothing is hardcoded):
  INPUT_PRICE_PER_MILLION, OUTPUT_PRICE_PER_MILLION   price per million tokens, in whatever currency you use
  COST_CEILING_PER_DOCUMENT                           same currency; needs both prices to work
Without prices, cost is reported as None and the ceiling is ignored.

State lives in the same SQLite file as the pack store (T8). It moves to Postgres once Docker works.
"""
import sys
import os
import json
import time
import uuid
import hashlib
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pack_store
from extract_clauses import extract_clauses
from compare_clauses import compare_clause_lists

FAILED_RISK_LEVELS = ("Error", "Unknown")  # what classify_clause returns when a call or its parsing fails

NEW_CLAUSE_COLUMNS = {"input_tokens": "INTEGER", "output_tokens": "INTEGER",
                      "latency_ms": "INTEGER", "duration_ms": "INTEGER"}


def settings():
    """Read at call time, so they can be changed in .env or the environment without touching code."""
    def num(name):
        v = os.environ.get(name)
        return float(v) if v not in (None, "") else None
    return {
        "max_workers": int(os.environ.get("MAX_CONCURRENT_CALLS", "4")),
        "max_retries": int(os.environ.get("MAX_RETRIES", "3")),
        "retry_base_seconds": float(os.environ.get("RETRY_BASE_SECONDS", "2")),
        "input_price": num("INPUT_PRICE_PER_MILLION"),
        "output_price": num("OUTPUT_PRICE_PER_MILLION"),
        "ceiling": num("COST_CEILING_PER_DOCUMENT"),
    }


def cost_of(input_tokens, output_tokens, cfg):
    if cfg["input_price"] is None or cfg["output_price"] is None:
        return None
    return input_tokens / 1e6 * cfg["input_price"] + output_tokens / 1e6 * cfg["output_price"]


def needs_classification(entry):
    """C3: a clause costs tokens only if its text changed. Unchanged clauses, and clauses that
    merely moved with identical text, are skipped."""
    if entry["status"] == "unchanged":
        return False
    if entry["status"] == "moved" and not entry.get("also_edited"):
        return False
    return True


def _now():
    return datetime.now(timezone.utc).isoformat()


def _connect():
    conn = pack_store._connect()  # same database file as the pack store
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clause_results (
            pair_hash       TEXT NOT NULL,
            position        INTEGER NOT NULL,
            heading         TEXT,
            change_status   TEXT,
            previous_text   TEXT,
            current_text    TEXT,
            state           TEXT NOT NULL,
            risk_level      TEXT,
            reason          TEXT,
            policy_rule     TEXT,
            attempts        INTEGER NOT NULL DEFAULT 0,
            last_error      TEXT,
            prompt_version  TEXT,
            model           TEXT,
            updated_at      TEXT,
            PRIMARY KEY (pair_hash, position)
        )
    """)
    have = {r[1] for r in conn.execute("PRAGMA table_info(clause_results)")}
    for col, typ in NEW_CLAUSE_COLUMNS.items():  # upgrade databases created by the earlier version
        if col not in have:
            conn.execute(f"ALTER TABLE clause_results ADD COLUMN {col} {typ}")
    conn.execute("""
        CREATE VIEW IF NOT EXISTS error_queue AS
        SELECT pair_hash, position, heading, attempts, last_error, updated_at
        FROM clause_results WHERE state = 'failed'
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS run_metrics (
            run_id            TEXT PRIMARY KEY,
            pair_hash         TEXT,
            started_at        TEXT,
            ended_at          TEXT,
            duration_ms       INTEGER,
            status            TEXT,
            stop_reason       TEXT,
            duplicate         INTEGER,
            resumed           INTEGER,
            clauses_total     INTEGER,
            clauses_skipped   INTEGER,
            clauses_processed INTEGER,
            model_calls       INTEGER,
            retries           INTEGER,
            failed_clauses    INTEGER,
            input_tokens      INTEGER,
            output_tokens     INTEGER,
            cost              REAL,
            document_cost     REAL,
            max_workers       INTEGER,
            prompt_version    TEXT,
            model             TEXT,
            risk_high         INTEGER,
            risk_medium       INTEGER,
            risk_low          INTEGER
        )
    """)
    conn.commit()
    return conn


def hash_clause_lists(previous_clauses, current_clauses):
    """Same hash as pack_store.compute_pair_hash, but on clauses that are already extracted.
    Must be computed before comparison, which adds fields to the clause dicts."""
    payload = {"previous": previous_clauses, "current": current_clauses}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def error_queue_depth():
    conn = _connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM error_queue").fetchone()[0]
    finally:
        conn.close()


def _process_clause(row, classify, cfg, sleep, gate, record):
    """Runs in a worker thread. Does no database work. Tries once, then retries with growing delay.
    Tokens are summed over every attempt, because a reply that fails to parse still costs tokens.
    gate() is asked before every attempt (the cost ceiling); record() reports tokens as soon as they are spent."""
    started = time.time()
    last_error = None
    attempts = 0
    tokens_in = tokens_out = 0
    latency_ms = None
    for k in range(cfg["max_retries"] + 1):
        if k > 0:
            delay = cfg["retry_base_seconds"] * (2 ** (k - 1))
            print(f"  retry {k}/{cfg['max_retries']} for '{row['heading']}' in {delay:g}s ({last_error})")
            sleep(delay)
        if not gate():
            return {"ok": False, "blocked": True, "attempts": attempts, "tokens_in": tokens_in,
                    "tokens_out": tokens_out, "latency_ms": latency_ms,
                    "duration_ms": int((time.time() - started) * 1000)}
        attempts += 1
        try:
            result = classify(row["heading"], row["previous_text"], row["current_text"])
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            continue
        usage = result.get("usage") or {}
        t_in, t_out = usage.get("input_tokens") or 0, usage.get("output_tokens") or 0
        tokens_in += t_in
        tokens_out += t_out
        record(t_in, t_out)
        latency_ms = usage.get("latency_ms", latency_ms)
        if result.get("risk_level") not in FAILED_RISK_LEVELS:
            return {"ok": True, "result": result, "attempts": attempts, "tokens_in": tokens_in,
                    "tokens_out": tokens_out, "latency_ms": latency_ms,
                    "duration_ms": int((time.time() - started) * 1000)}
        last_error = result.get("reason", "model call failed")
    return {"ok": False, "attempts": attempts, "error": last_error, "tokens_in": tokens_in,
            "tokens_out": tokens_out, "latency_ms": latency_ms,
            "duration_ms": int((time.time() - started) * 1000)}


def run_pair(previous_path, current_path, classify=None, prompt_version=None, model=None, sleep=time.sleep):
    """Processes one document pair. Returns a dict with:
       status ('complete' | 'partial'), stop_reason (None | 'clause_failures' | 'cost_ceiling'),
       duplicate, resumed, run_id, pair_hash, pack, failed (error queue), unprocessed (not attempted),
       skipped, clauses_processed, model_attempts, retries, input_tokens, output_tokens, cost, document_cost.
    A partial pack is returned but never stored as the pair's final pack."""
    run_started = time.time()
    run_id = uuid.uuid4().hex[:12]
    started_at = _now()
    cfg = settings()
    prev_clauses = extract_clauses(str(previous_path))
    curr_clauses = extract_clauses(str(current_path))
    pair_hash = hash_clause_lists(prev_clauses, curr_clauses)

    conn = _connect()

    def log_run(**kw):
        row = {"run_id": run_id, "pair_hash": pair_hash, "started_at": started_at, "ended_at": _now(),
               "duration_ms": int((time.time() - run_started) * 1000), "max_workers": cfg["max_workers"]}
        row.update(kw)
        cols = ", ".join(row)
        conn.execute(f"INSERT INTO run_metrics ({cols}) VALUES ({', '.join('?' for _ in row)})", list(row.values()))
        conn.commit()

    try:
        # Known pair with a stored complete pack: return it, no model call (A3)
        stored = conn.execute("SELECT pack_json FROM packs WHERE pair_hash = ?", (pair_hash,)).fetchone()
        if stored:
            conn.execute("UPDATE packs SET delivery_count = delivery_count + 1 WHERE pair_hash = ?", (pair_hash,))
            conn.commit()
            log_run(status="complete", duplicate=1, resumed=0, model_calls=0, retries=0, failed_clauses=0,
                    clauses_processed=0, input_tokens=0, output_tokens=0)
            return {"status": "complete", "stop_reason": None, "duplicate": True, "resumed": False,
                    "run_id": run_id, "pair_hash": pair_hash, "pack": json.loads(stored[0]), "failed": [],
                    "unprocessed": [], "skipped": {}, "clauses_processed": 0, "model_attempts": 0,
                    "retries": 0, "input_tokens": 0, "output_tokens": 0, "cost": None, "document_cost": None}

        comparison = compare_clause_lists(prev_clauses, curr_clauses)
        skipped_moved = [e["heading"] for e in comparison if e["status"] == "moved" and not e.get("also_edited")]
        n_skipped = sum(1 for e in comparison if not needs_classification(e))
        for h in skipped_moved:
            print(f"  skipped '{h}': moved, text unchanged")

        existing = conn.execute("SELECT COUNT(*) FROM clause_results WHERE pair_hash = ?", (pair_hash,)).fetchone()[0]
        resumed = existing > 0
        if not resumed:
            for position, entry in enumerate(comparison):
                if not needs_classification(entry):
                    continue  # C3: never sent to the model
                conn.execute(
                    "INSERT INTO clause_results (pair_hash, position, heading, change_status, previous_text, "
                    "current_text, state, attempts, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?)",
                    (pair_hash, position, entry["heading"], entry["status"],
                     entry["previous_text"], entry["current_text"], _now()),
                )
            conn.commit()

        if classify is None:
            from classify_clauses import classify_clause, PROMPT_VERSION, DEPLOYMENT_NAME
            classify = classify_clause
            prompt_version = prompt_version or PROMPT_VERSION
            model = model or DEPLOYMENT_NAME

        ceiling = cfg["ceiling"]
        if ceiling is not None and (cfg["input_price"] is None or cfg["output_price"] is None):
            print("  WARNING: COST_CEILING_PER_DOCUMENT is set but the token prices are not, so the ceiling is ignored.")
            ceiling = None

        # Tokens already spent on this pair in earlier runs count towards its ceiling
        base_in, base_out = conn.execute(
            "SELECT COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0) "
            "FROM clause_results WHERE pair_hash = ?", (pair_hash,)).fetchone()
        run_in = run_out = 0

        # Shared by all workers: each one checks the running cost before it starts a call, so the
        # overshoot past the ceiling is limited to the calls already in flight.
        spend = {"lock": threading.Lock(), "in": base_in, "out": base_out, "stopped": False}

        def gate():
            if ceiling is None:
                return True
            with spend["lock"]:
                if spend["stopped"]:
                    return False
                if cost_of(spend["in"], spend["out"], cfg) >= ceiling:
                    spend["stopped"] = True
                    return False
                return True

        def record(t_in, t_out):
            with spend["lock"]:
                spend["in"] += t_in
                spend["out"] += t_out

        cols = ["position", "heading", "previous_text", "current_text"]
        todo = [dict(zip(cols, r)) for r in conn.execute(
            "SELECT position, heading, previous_text, current_text FROM clause_results "
            "WHERE pair_hash = ? AND state != 'done' ORDER BY position", (pair_hash,)).fetchall()]

        total_attempts = 0
        retries = 0
        processed = 0
        if todo:
            print(f"Processing {len(todo)} clause(s) with up to {cfg['max_workers']} at a time"
                  f"{' (resuming)' if resumed else ''}...")
        with ThreadPoolExecutor(max_workers=cfg["max_workers"]) as pool:
            futures = {pool.submit(_process_clause, r, classify, cfg, sleep, gate, record): r for r in todo}
            for fut in as_completed(futures):
                r = futures[fut]
                out = fut.result()
                total_attempts += out["attempts"]
                retries += max(0, out["attempts"] - 1)
                run_in += out["tokens_in"]
                run_out += out["tokens_out"]
                if out.get("blocked"):
                    # Stopped by the cost ceiling: keep whatever was spent, leave the clause as it was
                    conn.execute(
                        "UPDATE clause_results SET attempts=attempts+?, updated_at=?, "
                        "input_tokens=COALESCE(input_tokens,0)+?, output_tokens=COALESCE(output_tokens,0)+? "
                        "WHERE pair_hash=? AND position=?",
                        (out["attempts"], _now(), out["tokens_in"], out["tokens_out"], pair_hash, r["position"]),
                    )
                    conn.commit()
                    continue
                processed += 1
                if out["ok"]:
                    res = out["result"]
                    conn.execute(
                        "UPDATE clause_results SET state='done', risk_level=?, reason=?, policy_rule=?, "
                        "attempts=attempts+?, last_error=NULL, prompt_version=?, model=?, updated_at=?, "
                        "input_tokens=COALESCE(input_tokens,0)+?, output_tokens=COALESCE(output_tokens,0)+?, "
                        "latency_ms=?, duration_ms=? WHERE pair_hash=? AND position=?",
                        (res.get("risk_level"), res.get("reason"), res.get("policy_rule_touched"),
                         out["attempts"], prompt_version, model, _now(), out["tokens_in"], out["tokens_out"],
                         out["latency_ms"], out["duration_ms"], pair_hash, r["position"]),
                    )
                else:
                    conn.execute(
                        "UPDATE clause_results SET state='failed', attempts=attempts+?, last_error=?, updated_at=?, "
                        "input_tokens=COALESCE(input_tokens,0)+?, output_tokens=COALESCE(output_tokens,0)+?, "
                        "latency_ms=?, duration_ms=? WHERE pair_hash=? AND position=?",
                        (out["attempts"], out["error"], _now(), out["tokens_in"], out["tokens_out"],
                         out["latency_ms"], out["duration_ms"], pair_hash, r["position"]),
                    )
                    print(f"  moved to error queue: '{r['heading']}' ({out['error']})")
                conn.commit()  # saved as it completes, so a crash keeps finished work (R8)

        stopped = spend["stopped"]
        if stopped:
            print(f"  cost ceiling {ceiling:g} reached: remaining clauses were not sent "
                  f"(calls already in flight finished)")

        # Assemble the pack in a stable order (C7), whatever order the threads finished in
        pack, failed, unprocessed = [], [], []
        for pos, heading, cstatus, ptext, ctext, state, risk, reason, rule in conn.execute(
            "SELECT position, heading, change_status, previous_text, current_text, state, risk_level, reason, policy_rule "
            "FROM clause_results WHERE pair_hash = ? ORDER BY position", (pair_hash,)).fetchall():
            if state == "done":
                pack.append({"heading": heading, "status": cstatus, "previous_text": ptext, "current_text": ctext,
                             "risk_level": risk, "reason": reason, "policy_rule_touched": rule})
            elif state == "failed":
                failed.append(heading)
            else:
                unprocessed.append(heading)

        status = "complete" if not failed and not unprocessed else "partial"
        stop_reason = None
        if status == "partial":
            stop_reason = "cost_ceiling" if stopped else "clause_failures"
        if status == "complete":
            conn.execute(
                "INSERT OR REPLACE INTO packs (pair_hash, previous_file, current_file, prompt_version, model, created_at, pack_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pair_hash, Path(previous_path).name, Path(current_path).name, prompt_version, model, _now(), json.dumps(pack)),
            )
            conn.commit()

        doc_in, doc_out = base_in + run_in, base_out + run_out
        run_cost = cost_of(run_in, run_out, cfg)
        doc_cost = cost_of(doc_in, doc_out, cfg)
        mix = {k: sum(1 for e in pack if e["risk_level"] == k) for k in ("High", "Medium", "Low")}
        log_run(status=status, stop_reason=stop_reason, duplicate=0, resumed=int(resumed),
                clauses_total=len(comparison), clauses_skipped=n_skipped, clauses_processed=processed,
                model_calls=total_attempts, retries=retries, failed_clauses=len(failed),
                input_tokens=run_in, output_tokens=run_out, cost=run_cost, document_cost=doc_cost,
                prompt_version=prompt_version, model=model,
                risk_high=mix["High"], risk_medium=mix["Medium"], risk_low=mix["Low"])

        return {"status": status, "stop_reason": stop_reason, "duplicate": False, "resumed": resumed,
                "run_id": run_id, "pair_hash": pair_hash, "pack": pack, "failed": failed,
                "unprocessed": unprocessed,
                "skipped": {"total": n_skipped, "moved_text_unchanged": skipped_moved},
                "clauses_processed": processed, "model_attempts": total_attempts, "retries": retries,
                "input_tokens": run_in, "output_tokens": run_out, "cost": run_cost, "document_cost": doc_cost}
    finally:
        conn.close()