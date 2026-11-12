import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from paths import SOW_DIR, OUTPUTS_DIR
import classify_clauses as cc
import pack_store

# Count every model call made through the classifier.
calls = {"n": 0}
_original = cc.classify_clause


def counted(*args, **kwargs):
    calls["n"] += 1
    return _original(*args, **kwargs)


cc.classify_clause = counted

# Use a throwaway database so the test is repeatable and never touches real packs.
pack_store.DB_PATH = OUTPUTS_DIR / "test_pack_store.db"
if pack_store.DB_PATH.exists():
    pack_store.DB_PATH.unlink()

prev = SOW_DIR / "sow_pair1_previous.docx"
curr = SOW_DIR / "sow_pair1_current.docx"

pack1, dup1, h1 = pack_store.process_pair(prev, curr)
calls_first = calls["n"]

pack2, dup2, h2 = pack_store.process_pair(prev, curr)
calls_second = calls["n"] - calls_first

print("\n" + "=" * 60)
print("DUPLICATE DELIVERY TEST (A3)")
print("=" * 60)
print(f"Pair hash: {h1[:16]}...")
print(f"Delivery 1: duplicate={dup1}, model calls={calls_first}, changed clauses in pack={len(pack1)}")
print(f"Delivery 2: duplicate={dup2}, model calls={calls_second}")
print(f"Same pack returned: {pack1 == pack2}")

ok = (not dup1) and dup2 and calls_first > 0 and calls_second == 0 and pack1 == pack2
print("\nPASS: repeat delivery returned the first pack with zero model calls." if ok else
      "\nFAIL: see the numbers above. If delivery 1 had API errors, the pack was not stored, so delivery 2 reprocessed it.")