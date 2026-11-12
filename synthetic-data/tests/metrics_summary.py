"""
Summary of the performance table (section 12 / section 11 'summary query').
Reads run_metrics and clause_results from the pack database. Run it any time.
"""
import sys
import sqlite3
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pack_store
from paths import OUTPUTS_DIR

# Optional: name another database in outputs/, e.g.  python tests\metrics_summary.py test_cost_ceiling.db
if len(sys.argv) > 1:
    pack_store.DB_PATH = OUTPUTS_DIR / sys.argv[1]

if not pack_store.DB_PATH.exists():
    print(f"No database yet at {pack_store.DB_PATH}")
    sys.exit(0)

conn = sqlite3.connect(pack_store.DB_PATH)
conn.row_factory = sqlite3.Row
try:
    runs = [dict(r) for r in conn.execute("SELECT * FROM run_metrics ORDER BY started_at")]
except sqlite3.OperationalError:
    print("The database has no run_metrics table yet. Run the pipeline once first.")
    sys.exit(0)

work = [r for r in runs if not r["duplicate"]]
dups = [r for r in runs if r["duplicate"]]

print("=" * 60)
print(f"PERFORMANCE SUMMARY  ({pack_store.DB_PATH.name})")
print("=" * 60)
print(f"Deliveries: {len(runs)}   processing runs: {len(work)}   duplicate deliveries caught: {len(dups)}")
if work:
    complete = [r for r in work if r["status"] == "complete"]
    clean = [r for r in complete if (r["failed_clauses"] or 0) == 0]
    print(f"Processing runs complete: {len(complete)}   partial: {len(work) - len(complete)}   "
          f"complete with no failed clauses: {len(clean)} ({len(clean) / len(work):.0%})")

    durs = [r["duration_ms"] for r in work]
    print(f"Run duration (ms): mean {sum(durs) / len(durs):.0f}   max {max(durs)}")

    first = [r for r in work if not r["resumed"]]  # a resumed run would count the same clauses again
    tot = sum(r["clauses_total"] or 0 for r in first)
    skp = sum(r["clauses_skipped"] or 0 for r in first)
    print(f"Clauses skipped (no model call): {skp} of {tot}" + (f" ({skp / tot:.0%})" if tot else ""))
    print(f"Model calls: {sum(r['model_calls'] or 0 for r in work)}   retries: {sum(r['retries'] or 0 for r in work)}")
    print(f"Tokens: {sum(r['input_tokens'] or 0 for r in work)} in / {sum(r['output_tokens'] or 0 for r in work)} out")

    costs = [r["cost"] for r in work if r["cost"] is not None]
    print(f"Cost: {sum(costs):.4f}" if costs else "Cost: not priced (set INPUT_PRICE_PER_MILLION and OUTPUT_PRICE_PER_MILLION)")

    per_doc = conn.execute(
        "SELECT pair_hash, MAX(document_cost) AS c FROM run_metrics WHERE document_cost IS NOT NULL GROUP BY pair_hash"
    ).fetchall()
    if per_doc:
        vals = [r["c"] for r in per_doc]
        print(f"Cost per document: mean {sum(vals) / len(vals):.4f}   max {max(vals):.4f}   ({len(vals)} documents)")

    mix = dict(conn.execute("SELECT risk_level, COUNT(*) FROM clause_results WHERE state = 'done' GROUP BY risk_level").fetchall())
    print(f"Risk mix (classified clauses): High {mix.get('High', 0)}   Medium {mix.get('Medium', 0)}   Low {mix.get('Low', 0)}")

    rates = [r["clauses_processed"] / (r["duration_ms"] / 60000) / r["max_workers"]
             for r in work if r["clauses_processed"] and r["duration_ms"] and r["max_workers"]]
    if rates:
        print(f"Worker throughput: {sum(rates) / len(rates):.1f} clauses per worker per minute (mean over runs)")

clause = conn.execute(
    "SELECT COUNT(*) n, AVG(duration_ms) d, MAX(duration_ms) dm, AVG(latency_ms) l, MAX(latency_ms) lm "
    "FROM clause_results WHERE state = 'done' AND duration_ms IS NOT NULL").fetchone()
if clause["n"]:
    print(f"Per clause ({clause['n']} done): duration mean {clause['d']:.0f} ms, max {clause['dm']} ms;  "
          f"model latency mean {clause['l']:.0f} ms, max {clause['lm']} ms")
try:
    depth = conn.execute("SELECT COUNT(*) FROM error_queue").fetchone()[0]
    print(f"Error queue depth now: {depth}")
except sqlite3.OperationalError:
    pass
conn.close()