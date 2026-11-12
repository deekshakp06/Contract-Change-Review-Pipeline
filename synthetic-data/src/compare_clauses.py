from extract_clauses import extract_clauses
from difflib import SequenceMatcher
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from paths import SOW_DIR


def normalize_heading(heading):
    """Strips a leading clause number (e.g. '2. Termination' -> 'termination')
    so clauses can be matched by content even if renumbered."""
    stripped = re.sub(r'^\s*\d+[\.\)]\s*', '', heading)
    return stripped.strip().lower()


def similarity(a, b):
    """Simple text similarity score between 0 and 1."""
    return SequenceMatcher(None, a, b).ratio()


def match_clauses(previous_clauses, current_clauses, match_threshold=0.5):
    """Pairs previous clauses with current clauses. Returns (matched_prev, matched_curr),
    two dicts mapping clause index -> index of its partner.

    Phase 1 pairs clauses whose normalized heading AND text are identical. These are the
    only pairs that can score exactly 1.0, so the original all-pairs scoring would have
    consumed them first anyway; doing them directly skips most of the work.
    Phase 2 scores only the leftover clauses against each other (fuzzy match).
    The result is identical to scoring every pair, just much faster when most clauses
    are unchanged."""
    matched_prev, matched_curr = {}, {}

    # Phase 1: exact matches. Duplicates are paired in document order, as before.
    prev_by_key, curr_by_key = {}, {}
    for c in previous_clauses:
        prev_by_key.setdefault((c["norm_heading"], c["text"]), []).append(c["index"])
    for c in current_clauses:
        curr_by_key.setdefault((c["norm_heading"], c["text"]), []).append(c["index"])
    for key, p_list in prev_by_key.items():
        c_list = curr_by_key.get(key)
        if not c_list:
            continue
        for p_idx, c_idx in zip(sorted(p_list), sorted(c_list)):
            matched_prev[p_idx] = c_idx
            matched_curr[c_idx] = p_idx

    # Phase 2: fuzzy matching among clauses that are still unmatched.
    left_prev = [c for c in previous_clauses if c["index"] not in matched_prev]
    left_curr = [c for c in current_clauses if c["index"] not in matched_curr]

    candidates = []
    for p in left_prev:
        for c in left_curr:
            heading_sim = similarity(p["norm_heading"], c["norm_heading"])
            text_sim = similarity(p["text"], c["text"])
            score = (0.6 * heading_sim) + (0.4 * text_sim)
            if score >= match_threshold:
                candidates.append((score, p["index"], c["index"]))

    # Greedily assign best matches first, each clause used at most once
    candidates.sort(reverse=True, key=lambda x: x[0])
    for score, p_idx, c_idx in candidates:
        if p_idx in matched_prev or c_idx in matched_curr:
            continue
        matched_prev[p_idx] = c_idx
        matched_curr[c_idx] = p_idx

    return matched_prev, matched_curr


def compare_clause_lists(previous_clauses, current_clauses, match_threshold=0.5):
    """Classifies each clause as unchanged, edited, moved, added, or removed (C1, C2).

    Matching combines normalized heading similarity and body text similarity, NOT exact
    heading/position alone, so a renumbered or reordered clause is still found
    (C1: 'handle a moved clause, a renumbered clause')."""
    # Attach original index (position) to each clause
    for i, c in enumerate(previous_clauses):
        c["index"] = i
        c["norm_heading"] = normalize_heading(c["heading"])
    for i, c in enumerate(current_clauses):
        c["index"] = i
        c["norm_heading"] = normalize_heading(c["heading"])

    matched_prev, matched_curr = match_clauses(previous_clauses, current_clauses, match_threshold)

    results = []

    # Classify matched and removed clauses (iterate previous version in order)
    for p in previous_clauses:
        p_idx = p["index"]
        if p_idx not in matched_prev:
            results.append({
                "heading": p["heading"],
                "status": "removed",
                "previous_text": p["text"],
                "current_text": None
            })
            continue

        c_idx = matched_prev[p_idx]
        c = current_clauses[c_idx]

        text_same = (p["text"] == c["text"])
        position_same = (p_idx == c_idx)

        if text_same and position_same:
            status = "unchanged"
        elif text_same and not position_same:
            status = "moved"
        elif not text_same and position_same:
            status = "edited"
        else:
            # Position changed AND text changed — treat as moved,
            # but flag that content also changed for reviewer visibility.
            status = "moved"

        entry = {
            "heading": c["heading"],
            "status": status,
            "previous_text": p["text"],
            "current_text": c["text"]
        }
        if status == "moved" and not text_same:
            entry["also_edited"] = True
        results.append(entry)

    # Any current clause never matched to a previous one = added
    for c in current_clauses:
        if c["index"] not in matched_curr:
            results.append({
                "heading": c["heading"],
                "status": "added",
                "previous_text": None,
                "current_text": c["text"]
            })

    return results


def compare_versions(previous_path, current_path, match_threshold=0.5):
    """Compares two SOW files. Same behaviour as before; the work is in compare_clause_lists."""
    return compare_clause_lists(
        extract_clauses(previous_path),
        extract_clauses(current_path),
        match_threshold,
    )


if __name__ == "__main__":
    results = compare_versions(str(SOW_DIR / "sow_pair1_previous.docx"), str(SOW_DIR / "sow_pair1_current.docx"))

    print(f"Compared {len(results)} clauses:\n")
    for r in results:
        extra = " (also edited)" if r.get("also_edited") else ""
        print(f"[{r['status'].upper()}]{extra} {r['heading']}")

    changed_count = sum(1 for r in results if r["status"] != "unchanged")
    print(f"\n{changed_count} clause(s) changed out of {len(results)} total.")