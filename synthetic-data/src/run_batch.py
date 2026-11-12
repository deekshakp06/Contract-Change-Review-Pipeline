"""
Night batch (A1): processes every document pair in a folder with no manual help.

  python src\\run_batch.py            the 20 synthetic pairs (sow_pair1 ... sow_pair20)
  python src\\run_batch.py --all      every *_previous.docx that has a matching *_current.docx

- One broken document never stops the batch: it is reported and the next pair starts.
- Safe to run twice: pairs that already have a stored pack come back as duplicates with no model call.
- Results go to the real pack database (outputs/pack_store.db), so metrics_summary.py shows them.
- A report is written to outputs/batch_report.json.
"""
import sys
import re
import json
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from paths import SOW_DIR, OUTPUTS_DIR
import clause_runner

parser = argparse.ArgumentParser(description="Process every document pair in a folder.")
parser.add_argument("--folder", default=str(SOW_DIR))
parser.add_argument("--all", action="store_true", help="include every matching pair, not just sow_pair<N>")
args = parser.parse_args()


def natural_key(text):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text)]


def discover(folder, include_all):
    pairs = []
    for prev in Path(folder).glob("*_previous.docx"):
        stem = prev.name[: -len("_previous.docx")]
        curr = Path(folder) / f"{stem}_current.docx"
        if not curr.exists():
            print(f"  skipping {stem}: no matching _current.docx")
            continue
        if not include_all and not re.fullmatch(r"sow_pair\d+", stem):
            continue
        pairs.append((stem, prev, curr))
    return sorted(pairs, key=lambda p: natural_key(p[0]))


pairs = discover(args.folder, args.all)
print(f"Batch started: {len(pairs)} pair(s) in {args.folder}\n")

started_at = datetime.now(timezone.utc).isoformat()
batch_t0 = time.time()
rows = []
for i, (stem, prev, curr) in enumerate(pairs, start=1):
    t0 = time.time()
    try:
        r = clause_runner.run_pair(prev, curr)
        high = sum(1 for e in r["pack"] if e["risk_level"] == "High")
        row = {"pair": stem, "outcome": r["status"], "duplicate": r["duplicate"], "resumed": r["resumed"],
               "classified": len(r["pack"]), "high_risk": high, "failed": len(r["failed"]),
               "unprocessed": len(r["unprocessed"]), "model_calls": r["model_attempts"], "retries": r["retries"],
               "input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"], "cost": r["cost"],
               "seconds": round(time.time() - t0, 1)}
        if r["duplicate"]:
            detail = "duplicate: stored pack returned, 0 model calls"
        else:
            detail = (f"classified={row['classified']} high={high} calls={row['model_calls']} "
                      f"tokens={row['input_tokens'] + row['output_tokens']}")
        print(f"[{i:>2}/{len(pairs)}] {stem:<14} {r['status']:<9} {detail}  ({row['seconds']}s)")
    except Exception as e:  # one broken document must not stop the batch
        row = {"pair": stem, "outcome": "error", "error": f"{type(e).__name__}: {e}",
               "seconds": round(time.time() - t0, 1)}
        print(f"[{i:>2}/{len(pairs)}] {stem:<14} ERROR     {row['error']}")
    rows.append(row)

duration = time.time() - batch_t0
done = [r for r in rows if r["outcome"] == "complete"]
dups = [r for r in rows if r.get("duplicate")]
partial = [r for r in rows if r["outcome"] == "partial"]
errors = [r for r in rows if r["outcome"] == "error"]
calls = sum(r.get("model_calls", 0) for r in rows)
tok_in = sum(r.get("input_tokens", 0) for r in rows)
tok_out = sum(r.get("output_tokens", 0) for r in rows)
costs = [r["cost"] for r in rows if r.get("cost") is not None]

print("\n" + "=" * 60)
print("BATCH SUMMARY")
print("=" * 60)
print(f"Pairs: {len(rows)}   complete: {len(done)} (of which duplicates: {len(dups)})   "
      f"partial: {len(partial)}   errors: {len(errors)}")
print(f"Model calls: {calls}   tokens: {tok_in} in / {tok_out} out   "
      f"cost: {sum(costs):.4f}" if costs else
      f"Model calls: {calls}   tokens: {tok_in} in / {tok_out} out   cost: not priced")
print(f"High-risk changes routed for review: {sum(r.get('high_risk', 0) for r in rows)}")
print(f"Wall time: {duration:.1f}s")

report = {"started_at": started_at, "duration_seconds": round(duration, 1), "pairs": rows,
          "totals": {"pairs": len(rows), "complete": len(done), "duplicates": len(dups), "partial": len(partial),
                     "errors": len(errors), "model_calls": calls, "input_tokens": tok_in, "output_tokens": tok_out}}
with open(OUTPUTS_DIR / "batch_report.json", "w") as f:
    json.dump(report, f, indent=2)
print(f"Report saved to {OUTPUTS_DIR / 'batch_report.json'}")

sys.exit(0 if not partial and not errors else 1)