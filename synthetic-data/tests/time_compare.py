import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from paths import SOW_DIR
import compare_clauses
from extract_clauses import extract_clauses

prev = SOW_DIR / "sow_large200_previous.docx"
curr = SOW_DIR / "sow_large200_current.docx"

print(f"Python {sys.version.split()[0]}")
print(f"New matching code loaded: {hasattr(compare_clauses, 'match_clauses')}")

t0 = time.time()
prev_clauses = extract_clauses(str(prev))
t1 = time.time()
curr_clauses = extract_clauses(str(curr))
t2 = time.time()
results = compare_clauses.compare_clause_lists(prev_clauses, curr_clauses)
t3 = time.time()

print(f"\nRead previous document : {t1 - t0:.2f}s  ({len(prev_clauses)} clauses)")
print(f"Read current document  : {t2 - t1:.2f}s  ({len(curr_clauses)} clauses)")
print(f"Matching and comparing : {t3 - t2:.2f}s")
print(f"Total                  : {t3 - t0:.2f}s")