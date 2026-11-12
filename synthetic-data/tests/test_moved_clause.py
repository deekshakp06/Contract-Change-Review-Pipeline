import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from paths import SOW_DIR, OUTPUTS_DIR
from docx import Document
from compare_clauses import compare_versions


def create_reordered_version():
    """Creates a test 'current' version where clause 2 (Termination) and
    clause 7 (Governing Law) have swapped positions, with no text changes.
    This simulates a renumbered/reordered clause (C1 test case)."""

    clauses_in_order = [
        ("1. Payment Terms", "Payment shall be made within 30 days of invoice receipt."),
        ("2. Governing Law", "This agreement shall be governed by the laws of the state in which the client's principal office is located."),
        ("3. Liability", "The vendor's total liability shall not exceed the total fees paid in the preceding 12 months."),
        ("4. Confidentiality", "Both parties shall maintain confidentiality for a period of 5 years following termination."),
        ("5. Intellectual Property", "All intellectual property created under this agreement shall be owned by the client upon full payment."),
        ("6. Warranties", "The vendor warrants that all deliverables shall be free from material defects for a period of 90 days following delivery."),
        ("7. Termination", "Either party may terminate this agreement with 60 days written notice."),
        ("8. Data Protection", "The vendor shall implement industry-standard data protection measures and comply with applicable data privacy laws."),
        ("9. Dispute Resolution", "Any dispute arising under this agreement shall first be resolved through good-faith negotiation, followed by binding arbitration if unresolved within 30 days."),
        ("10. Force Majeure", "Neither party shall be liable for delays caused by events beyond their reasonable control, including natural disasters, war, or government action."),
        ("11. Subcontracting", "The vendor shall not subcontract any part of this engagement without the client's prior written consent."),
    ]

    doc = Document()
    doc.add_heading("Test Reordered SOW", level=1)
    for heading, text in clauses_in_order:
        doc.add_heading(heading, level=2)
        doc.add_paragraph(text)

    output_path = OUTPUTS_DIR / "sow_pair1_reordered_test.docx"
    doc.save(str(output_path))
    print(f"Created {output_path} (Termination and Governing Law swapped positions)")
    return output_path


if __name__ == "__main__":
    reordered_path = create_reordered_version()

    results = compare_versions(
        str(SOW_DIR / "sow_pair1_previous.docx"),
        str(reordered_path)
    )

    print(f"\nCompared {len(results)} clauses:\n")
    for r in results:
        extra = " (also edited)" if r.get("also_edited") else ""
        print(f"[{r['status'].upper()}]{extra} {r['heading']}")

    moved_count = sum(1 for r in results if r["status"] == "moved")
    removed_count = sum(1 for r in results if r["status"] == "removed")
    added_count = sum(1 for r in results if r["status"] == "added")

    print(f"\n{'='*50}")
    print(f"Moved: {moved_count} | Removed: {removed_count} | Added: {added_count}")

    if moved_count == 2 and removed_count == 0 and added_count == 0:
        print("PASS — both reordered clauses correctly detected as MOVED, not removed/added.")
    else:
        print("FAIL — reordered clauses were not correctly detected as moved.")