"""
Generates one large previous/current SOW pair (default 200 clauses) with a known set of
edited clauses, writes the ground truth, then runs compare_versions on the pair and
checks it flagged exactly the edited clauses (A2 prerequisite, R1).

Usage (from the project root):
    python src\\generate_large_pair.py
    python src\\generate_large_pair.py --clauses 200 --changed 40
"""
import sys
import json
import time
import random
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from docx import Document
from paths import SOW_DIR, DATA_DIR
from compare_clauses import compare_versions

parser = argparse.ArgumentParser()
parser.add_argument("--clauses", type=int, default=200)
parser.add_argument("--changed", type=int, default=40)
parser.add_argument("--seed", type=int, default=1)
args = parser.parse_args()

TYPES = [
    ("Payment Terms", "Payment for work package {i} shall be made within {n} days of invoice receipt."),
    ("Termination", "Either party may terminate work package {i} with {n} days written notice."),
    ("Liability", "The vendor's liability for work package {i} shall not exceed fees paid in the preceding {n} months."),
    ("Confidentiality", "Both parties shall keep work package {i} information confidential for {n} years following termination."),
    ("Warranties", "Deliverables for work package {i} are warranted free from material defects for {n} days after delivery."),
    ("Data Protection", "The vendor shall apply data protection level {n} to all data handled in work package {i}."),
    ("Subcontracting", "Subcontracting under work package {i} requires written consent given within {n} business days."),
    ("Dispute Resolution", "Disputes under work package {i} go to arbitration if not settled within {n} days."),
    ("Force Majeure", "Delays to work package {i} caused by events beyond control are excused for up to {n} days."),
    ("Governing Law", "Work package {i} is governed by the laws of jurisdiction code {n}."),
]
BASE_N = [30, 60, 12, 5, 90, 2, 5, 30, 30, 1]


def build(path, title, n_clauses, changed, edited):
    doc = Document()
    doc.add_heading(title, level=1)
    for i in range(1, n_clauses + 1):
        t = (i - 1) % len(TYPES)
        name, template = TYPES[t]
        n = BASE_N[t] + (7 if (edited and i in changed) else 0)
        doc.add_heading(f"{i}. {name} - Work Package {i}", level=2)
        doc.add_paragraph(template.format(i=i, n=n))
    doc.save(str(path))


random.seed(args.seed)
changed = set(random.sample(range(1, args.clauses + 1), min(args.changed, args.clauses)))

tag = f"sow_large{args.clauses}"
prev_path = SOW_DIR / f"{tag}_previous.docx"
curr_path = SOW_DIR / f"{tag}_current.docx"
build(prev_path, "Large SOW - Previous", args.clauses, changed, edited=False)
build(curr_path, "Large SOW - Current", args.clauses, changed, edited=True)

truth_path = DATA_DIR / f"{tag}_truth.json"
with open(truth_path, "w") as f:
    json.dump({"clauses": args.clauses, "edited_clause_numbers": sorted(changed)}, f, indent=2)

print(f"Created {prev_path.name} and {curr_path.name} ({args.clauses} clauses, {len(changed)} edited)")
print(f"Ground truth saved to {truth_path.name}")

t0 = time.time()
results = compare_versions(str(prev_path), str(curr_path))
elapsed = time.time() - t0
flagged = {int(r["heading"].split(".")[0]) for r in results if r["status"] != "unchanged"}
statuses = {}
for r in results:
    statuses[r["status"]] = statuses.get(r["status"], 0) + 1

print(f"\nComparison took {elapsed:.1f}s   statuses={statuses}")
if flagged == changed:
    print(f"PASS: flagged exactly the {len(changed)} edited clauses.")
else:
    print(f"FAIL: missing={sorted(changed - flagged)[:10]} extra={sorted(flagged - changed)[:10]}")