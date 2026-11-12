from docx import Document
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from paths import SOW_DIR

def extract_clauses(filepath):
    """Reads a SOW docx and extracts each clause as a structured record."""
    doc = Document(filepath)
    clauses = []
    current_heading = None
    current_text_parts = []

    for para in doc.paragraphs:
        style = para.style.name if para.style else ""

        # Heading 2 = a clause heading (e.g., "4. Payment Terms")
        if style == "Heading 2":
            # Save the previous clause before starting a new one
            if current_heading is not None:
                clauses.append({
                    "heading": current_heading,
                    "text": " ".join(current_text_parts).strip()
                })
            current_heading = para.text.strip()
            current_text_parts = []
            
        elif style != "Heading 1" and para.text.strip():
            current_text_parts.append(para.text.strip())

    # Save the last clause after the loop ends
    if current_heading is not None:
        clauses.append({
            "heading": current_heading,
            "text": " ".join(current_text_parts).strip()
        })

    return clauses


if __name__ == "__main__":
    clauses = extract_clauses(str(SOW_DIR / "sow_pair1_previous.docx"))
    print(f"Extracted {len(clauses)} clauses:\n")
    for c in clauses:
        print(f"- {c['heading']}: {c['text'][:60]}...")