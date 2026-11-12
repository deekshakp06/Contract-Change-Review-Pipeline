"""
R6: the run stops when the cost ceiling for a document is crossed, keeps the partial pack and marks it partial.
Then the ceiling is lifted and the same pair is delivered again: it resumes and no clause is sent twice.

The prices and ceiling below are TEST-ONLY numbers chosen so the ceiling trips after a handful of calls.
They are not real prices. Real prices go in .env (INPUT_PRICE_PER_MILLION, OUTPUT_PRICE_PER_MILLION).
Uses the 200-clause pair and the real classifier (about 40 API calls).
"""
import sys
import os
import json
import threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from paths import SOW_DIR, DATA_DIR, OUTPUTS_DIR
import classify_clauses as cc
import pack_store
import clause_runner

pack_store.DB_PATH = OUTPUTS_DIR / "test_cost_ceiling.db"
if pack_store.DB_PATH.exists():
    pack_store.DB_PATH.unlink()

os.environ["INPUT_PRICE_PER_MILLION"] = "1000"    # test-only
os.environ["OUTPUT_PRICE_PER_MILLION"] = "1000"   # test-only
os.environ["COST_CEILING_PER_DOCUMENT"] = "3.0"   # test-only: about 7 calls at roughly 450 tokens each
os.environ["MAX_CONCURRENT_CALLS"] = "4"

prev = SOW_DIR / "sow_large200_previous.docx"
curr = SOW_DIR / "sow_large200_current.docx"
with open(DATA_DIR / "sow_large200_truth.json") as f:
    n_edited = len(json.load(f)["edited_clause_numbers"])

lock = threading.Lock()
calls = {"n": 0}


def classify(heading, previous_text, current_text):
    with lock:
        calls["n"] += 1
    return cc.classify_clause(heading, previous_text, current_text)


def run():
    return clause_runner.run_pair(prev, curr, classify=classify,
                                  prompt_version=cc.PROMPT_VERSION, model=cc.DEPLOYMENT_NAME)


print("\n--- Run 1: ceiling 3.0 (test-only numbers) ---")
r1 = run()
calls1 = calls["n"]

print("\n--- Run 2: ceiling lifted, same pair delivered again ---")
os.environ.pop("COST_CEILING_PER_DOCUMENT")
r2 = run()
calls2 = calls["n"] - calls1

print("\n" + "=" * 60)
print("COST CEILING TEST (R6)")
print("=" * 60)
print(f"Run 1: status={r1['status']}  stop_reason={r1['stop_reason']}  done={len(r1['pack'])}  "
      f"unprocessed={len(r1['unprocessed'])}  error queue={len(r1['failed'])}  model calls={calls1}  "
      f"document cost={r1['document_cost']:.2f}")
print(f"Run 2: status={r2['status']}  resumed={r2['resumed']}  pack={len(r2['pack'])}  model calls={calls2}  "
      f"document cost={r2['document_cost']:.2f}")

checks = {
    "stopped at the ceiling with a partial pack": r1["status"] == "partial" and r1["stop_reason"] == "cost_ceiling"
        and 0 < len(r1["pack"]) < n_edited,
    "unsent clauses are not in the error queue": len(r1["failed"]) == 0 and len(r1["unprocessed"]) > 0,
    "run 1 overshoot is small (calls already in flight)": r1["document_cost"] < 3.0 + 4 * 1.0,
    "resume completed the document": r2["resumed"] and r2["status"] == "complete" and len(r2["pack"]) == n_edited,
    "no clause was sent twice": calls1 + calls2 == n_edited,
}
for name, ok in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'}: {name}")