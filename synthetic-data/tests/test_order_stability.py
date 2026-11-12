import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from paths import SOW_DIR
from compare_clauses import compare_versions


def test_order_stability(previous_path, current_path, runs=3):
    """Runs compare_versions multiple times on the same input and checks
    that the clause order is identical every time (C7 requirement)."""

    orderings = []
    for i in range(runs):
        results = compare_versions(previous_path, current_path)
        order = [r["heading"] for r in results]
        orderings.append(order)
        print(f"Run {i+1}: {order}")

    all_match = all(order == orderings[0] for order in orderings)

    print(f"\n{'='*50}")
    if all_match:
        print(f"PASS — all {runs} runs produced identical clause order (C7 satisfied).")
    else:
        print(f"FAIL — clause order differs between runs. C7 is NOT satisfied.")
        for i, order in enumerate(orderings):
            if order != orderings[0]:
                print(f"  Run {i+1} differs from Run 1.")

    return all_match


if __name__ == "__main__":
    test_order_stability(
        str(SOW_DIR / "sow_pair1_previous.docx"),
        str(SOW_DIR / "sow_pair1_current.docx"),
        runs=3
    )