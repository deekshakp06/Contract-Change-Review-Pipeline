"""
A4: five clauses fail on purpose -> they land in the error queue, the rest of the document completes.
A5: a re-delivery resumes and reprocesses only those five.
A3: a further re-delivery returns the stored pack with no model calls.
Uses the 200-clause pair from generate_large_pair.py and the real classifier (about 40 API calls).
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

os.environ["RETRY_BASE_SECONDS"] = "0.2"  # keep this test quick; the real default is 2s

# Throwaway database so the test is repeatable and never touches real packs
pack_store.DB_PATH = OUTPUTS_DIR / "test_reliability.db"
if pack_store.DB_PATH.exists():
    pack_store.DB_PATH.unlink()

prev = SOW_DIR / "sow_large200_previous.docx"
curr = SOW_DIR / "sow_large200_current.docx"
with open(DATA_DIR / "sow_large200_truth.json") as f:
    truth = json.load(f)
fail_numbers = set(truth["edited_clause_numbers"][:5])

inject = {"on": True}
lock = threading.Lock()
calls = {"n": 0}


def classify(heading, previous_text, current_text):
    if inject["on"] and int(heading.split(".")[0]) in fail_numbers:
        return {"risk_level": "Error", "reason": "injected failure", "policy_rule_touched": "N/A"}
    with lock:
        calls["n"] += 1
    return cc.classify_clause(heading, previous_text, current_text)


def run():
    return clause_runner.run_pair(prev, curr, classify=classify,
                                  prompt_version=cc.PROMPT_VERSION, model=cc.DEPLOYMENT_NAME)


print(f"\n--- Run 1: clauses {sorted(fail_numbers)} fail on purpose ---")
r1 = run()
calls1 = calls["n"]
queue1 = clause_runner.error_queue_depth()

print("\n--- Run 2: failures removed, same pair delivered again (resume) ---")
inject["on"] = False
calls["n"] = 0
r2 = run()
calls2 = calls["n"]
queue2 = clause_runner.error_queue_depth()

print("\n--- Run 3: same pair delivered a third time ---")
calls["n"] = 0
r3 = run()
calls3 = calls["n"]

print("\n" + "=" * 60)
print("RELIABILITY TEST")
print("=" * 60)
print(f"Run 1: status={r1['status']}  done={len(r1['pack'])}  failed={len(r1['failed'])}  "
      f"error queue depth={queue1}  model calls={calls1}  retries={r1['retries']}")
print(f"Run 2: status={r2['status']}  resumed={r2['resumed']}  pack={len(r2['pack'])}  "
      f"error queue depth={queue2}  model calls={calls2}")
print(f"Run 3: status={r3['status']}  duplicate={r3['duplicate']}  model calls={calls3}")

order_ok = [e["heading"] for e in r2["pack"]] == sorted(
    [e["heading"] for e in r2["pack"]], key=lambda h: int(h.split(".")[0]))
checks = {
    "A4 five failures queued, rest completed": r1["status"] == "partial" and len(r1["failed"]) == 5 and queue1 == 5
        and len(r1["pack"]) == len(r2["pack"]) - 5,
    "A5 resume reprocessed only the failed five": r2["resumed"] and calls2 == 5 and r2["status"] == "complete"
        and queue2 == 0 and len(r2["pack"]) == len(truth["edited_clause_numbers"]),
    "A3 repeat delivery made no model calls": r3["duplicate"] and calls3 == 0 and r3["pack"] == r2["pack"],
    "C7 pack in stable clause order": order_ok,
}
for name, ok in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'}: {name}")