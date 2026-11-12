"""
Shared path helper. Import this in any script so file paths work correctly
no matter which folder (src/, tests/) the script is actually run from.

Usage:
    from paths import DATA_DIR, SOW_DIR, OUTPUTS_DIR

    doc_path = SOW_DIR / "sow_pair1_previous.docx"
"""

from pathlib import Path

# This file lives in the project root (synthetic-data/), so PROJECT_ROOT
# is wherever paths.py itself is located.
PROJECT_ROOT = Path(__file__).resolve().parent

DATA_DIR = PROJECT_ROOT / "data"
SOW_DIR = DATA_DIR / "sow_documents"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
PROMPTS_DIR = PROJECT_ROOT / "prompts"

POLICY_CHECKLIST_PATH = DATA_DIR / "policy_checklist.json"
EVALUATION_SET_PATH = DATA_DIR / "evaluation_set_30.json"

