"""Run the 30-case evaluation through the n8n webhook and compare the risk levels
returned by the workflow with the answer key.

Usage (PowerShell, from the synthetic-data folder):
    $env:N8N_WEBHOOK_URL = "https://<your-n8n-host>/webhook/contract-pair"
    $env:N8N_WEBHOOK_SECRET = "<your webhook secret>"
    python tests\\run_n8n_evaluation.py

Use the PRODUCTION webhook URL (/webhook/...) if the workflow is published. With the
TEST URL (/webhook-test/...) the script pauses before each pair so you can click
'Listen for test event' on the Webhook node. The secret is read from the environment
and is never written to disk.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DOCS = BASE / "data" / "sow_documents"
CASES_FILE = BASE / "data" / "evaluation_set_30.json"
OUT_DIR = BASE / "outputs" / "n8n_eval"
RESULT_FILE = BASE / "outputs" / "n8n_evaluation.json"

PAUSE_SECONDS = 5      # pause between pairs
TIMEOUT_SECONDS = 600  # max wait for one pair
LEVELS = ("High", "Medium", "Low")


def norm(heading):
    return re.sub(r"^\s*\d+[\.\)]\s*", "", str(heading)).strip().lower()


def post_pair(url, secret, curl, previous, current):
    cmd = [
        curl, "-s", "-m", str(TIMEOUT_SECONDS), "-X", "POST", url,
        "-H", "X-Webhook-Secret: " + secret,
        "-F", "previous_file=@" + str(previous),
        "-F", "current_file=@" + str(current),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    return proc.stdout.strip(), proc.returncode


def extract_pack(raw):
    """Return (pack_dict_or_None, status_text)."""
    try:
        data = json.loads(raw)
    except Exception:
        return None, "response is not JSON"
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return None, "unexpected response shape"
    status = str(data.get("status", ""))
    pack = data.get("pack", data)
    if isinstance(pack, str):
        try:
            pack = json.loads(pack)
        except Exception:
            return None, "pack is not JSON"
    if isinstance(pack, dict) and "change_table" in pack:
        return pack, status or pack.get("status", "")
    return None, status or "no change_table in response"


def main():
    url = os.environ.get("N8N_WEBHOOK_URL")
    secret = os.environ.get("N8N_WEBHOOK_SECRET")
    if not url or not secret:
        sys.exit("Set N8N_WEBHOOK_URL and N8N_WEBHOOK_SECRET first (see the top of this file).")
    manual = "webhook-test" in url
    if manual:
        print("Test URL detected: before each pair, close any node panel and click 'Execute workflow' on the")
        print("n8n canvas (choose Webhook1), then press Enter here. Do NOT use 'Listen for test event' inside")
        print("the Webhook1 panel: that runs only that node. The test URL accepts one request per click.\n")
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        sys.exit("curl was not found on this machine.")

    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    pair_ids = sorted({c["pair_id"] for c in cases})
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    predicted = {}  # (pair_id, normalised heading) -> risk level
    for n, pid in enumerate(pair_ids, start=1):
        prev = DOCS / f"sow_pair{pid}_previous.docx"
        curr = DOCS / f"sow_pair{pid}_current.docx"
        if not prev.exists() or not curr.exists():
            print(f"[{n}/{len(pair_ids)}] pair {pid}: files not found, skipped")
            continue
        if manual:
            input(f"[{n}/{len(pair_ids)}] pair {pid}: on the n8n CANVAS click 'Execute workflow' (choose Webhook1), wait for 'Waiting for trigger event', then press Enter... ")
        started = time.time()
        raw, code = post_pair(url, secret, curl, prev, curr)
        (OUT_DIR / f"pair_{pid}.json").write_text(raw, encoding="utf-8")
        pack, status = extract_pack(raw)
        took = round(time.time() - started, 1)
        if pack is None:
            print(f"[{n}/{len(pair_ids)}] pair {pid}: no usable result ({status}); see outputs/n8n_eval/pair_{pid}.json  [{took}s]")
        else:
            for row in pack.get("change_table", []):
                predicted[(pid, norm(row.get("clause", "")))] = row.get("risk")
            failed = len(pack.get("error_queue", []))
            print(f"[{n}/{len(pair_ids)}] pair {pid}: {status or 'ok'}, {len(pack['change_table'])} classified, {failed} failed  [{took}s]")
        time.sleep(PAUSE_SECONDS)

    results = []
    for c in cases:
        got = predicted.get((c["pair_id"], norm(c["heading"])))
        results.append({
            "pair_id": c["pair_id"], "heading": c["heading"],
            "expected": c["risk_level"], "n8n": got,
            "match": got == c["risk_level"],
        })

    answered = [r for r in results if r["n8n"] in LEVELS]
    correct = sum(1 for r in results if r["match"])
    confusion = Counter((r["expected"], r["n8n"]) for r in answered if not r["match"])
    recall = {}
    for level in LEVELS:
        total = sum(1 for r in answered if r["expected"] == level)
        hit = sum(1 for r in answered if r["expected"] == level and r["match"])
        recall[level] = f"{hit}/{total}"

    summary = {
        "cases": len(results),
        "answered_by_n8n": len(answered),
        "not_answered": len(results) - len(answered),
        "correct": correct,
        "accuracy_percent_of_all_cases": round(100 * correct / len(results), 1),
        "accuracy_percent_of_answered": round(100 * correct / len(answered), 1) if answered else None,
        "correct_by_expected_level": recall,
        "misses": {f"{k[0]} -> {k[1]}": v for k, v in confusion.items()},
    }
    RESULT_FILE.write_text(json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 50)
    print("N8N EVALUATION SUMMARY")
    print("=" * 50)
    for k, v in summary.items():
        print(f"{k}: {v}")
    print(f"\nSaved to {RESULT_FILE}")


if __name__ == "__main__":
    main()