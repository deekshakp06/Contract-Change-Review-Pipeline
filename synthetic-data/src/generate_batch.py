from docx import Document
import json
import random

# Fixed seed so the output is IDENTICAL every time this script runs.
# Required: the doc calls this an "agreed" evaluation set (G5) and a reproducible "seed script" (T9) — a set that changes every run cannot be agreed upon or reliably re-tested against.
random.seed(42)

# ---------------------------------------------------------------------------
""" Clause bank: 10 clause types, each with a base (unchanged) version and one
or more variations. Each variation is a tuple of:
(new_text, risk_level, reason, policy_rule)
Every clause type contributes exactly one policy rule -> 10 rules total. """
# ---------------------------------------------------------------------------
CLAUSE_BANK = {
    "Payment Terms": {
        "base": "Payment shall be made within 30 days of invoice receipt.",
        "variations": [
            ("Payment shall be made within 45 days of invoice receipt.", "Low",
             "Minor extension within acceptable range.",
             "Payment terms must not exceed 45 days"),
            ("Payment shall be made within 90 days of invoice receipt.", "High",
             "Payment window extended well beyond policy limit.",
             "Payment terms must not exceed 45 days"),
        ]
    },
    "Termination": {
        "base": "Either party may terminate this agreement with 60 days written notice.",
        "variations": [
            ("Either party may terminate this agreement with 45 days written notice.", "Medium",
             "Notice period shortened but still reasonable.",
             "Termination notice period must not be less than 30 days"),
            ("Either party may terminate this agreement with 10 days written notice.", "High",
             "Notice period drastically reduced, insufficient response time.",
             "Termination notice period must not be less than 30 days"),
        ]
    },
    "Liability": {
        "base": "The vendor's total liability shall not exceed the total fees paid in the preceding 12 months.",
        "variations": [
            ("The vendor's total liability shall not exceed the total fees paid in the preceding 6 months.", "Medium",
             "Liability cap reduced, less protection for client.",
             "Liability cap must not be reduced below 12 months of contract value"),
            ("The vendor's liability shall be unlimited.", "High",
             "Liability cap removed entirely.",
             "Liability cap must not exceed 12 months of contract value"),
        ]
    },
    "Confidentiality": {
        "base": "Both parties shall maintain confidentiality for a period of 5 years following termination.",
        "variations": [
            ("Both parties shall maintain confidentiality for a period of 1 year following termination.", "High",
             "Confidentiality period drastically shortened.",
             "Confidentiality obligations must survive at least 3 years post-termination"),
            ("Both parties shall maintain confidentiality for a period of 3 years following termination.", "Low",
             "Confidentiality period slightly reduced but still meets minimum.",
             "Confidentiality obligations must survive at least 3 years post-termination"),
        ]
    },
    "Intellectual Property": {
        "base": "All intellectual property created under this agreement shall be owned by the client upon full payment.",
        "variations": [
            ("All intellectual property created under this agreement shall be jointly owned by both parties.", "High",
             "Client loses exclusive IP ownership.",
             "Client must retain full IP ownership upon payment"),
        ]
    },
    "Warranties": {
        "base": "The vendor warrants that all deliverables shall be free from material defects for a period of 90 days following delivery.",
        "variations": [
            ("The vendor warrants that all deliverables shall be free from material defects for a period of 30 days following delivery.", "Medium",
             "Warranty period shortened from 90 to 30 days.",
             "Warranty period must be at least 60 days"),
        ]
    },
    "Governing Law": {
        "base": "This agreement shall be governed by the laws of the state in which the client's principal office is located.",
        "variations": [
            ("This agreement shall be governed by the laws of the state in which the vendor's principal office is located.", "Medium",
             "Governing law jurisdiction shifted to vendor's favor.",
             "Governing law must default to client's jurisdiction"),
        ]
    },
    "Data Protection": {
        "base": "The vendor shall implement industry-standard data protection measures and comply with applicable data privacy laws.",
        "variations": [
            ("The vendor shall implement reasonable data protection measures where feasible.", "High",
             "Data protection obligation weakened from mandatory to discretionary.",
             "Data protection measures must be mandatory, not discretionary"),
        ]
    },
    "Dispute Resolution": {
        "base": "Any dispute arising under this agreement shall first be resolved through good-faith negotiation, followed by binding arbitration if unresolved within 30 days.",
        "variations": [
            ("Any dispute arising under this agreement shall be resolved solely through litigation in the vendor's chosen jurisdiction.", "High",
             "Arbitration path removed, forcing costly litigation in vendor-favored jurisdiction.",
             "Dispute resolution must include a mandatory arbitration step before litigation"),
        ]
    },
    "Force Majeure": {
        "base": "Neither party shall be liable for delays caused by events beyond their reasonable control, including natural disasters, war, or government action.",
        "variations": [
            ("Neither party shall be liable for delays caused by events beyond their reasonable control, including natural disasters, war, government action, or vendor staffing shortages.", "Medium",
             "Force majeure scope broadened to cover vendor's own staffing issues, reducing vendor accountability.",
             "Force majeure must not cover a party's own operational or staffing failures"),
        ]
    },
    "Subcontracting": {
        "base": "The vendor shall not subcontract any part of this engagement without the client's prior written consent.",
        "variations": [
            ("The vendor may subcontract any part of this engagement at its sole discretion.", "High",
             "Client's approval right over subcontracting removed entirely.",
             "Subcontracting requires the client's prior written consent"),
        ]
    },
}

# Sanity check: doc requires "at least ten" policy rules (3.1) -> at least 10 clause types
assert len(CLAUSE_BANK) >= 10, f"Expected at least 10 clause types, found {len(CLAUSE_BANK)}"


def build_document_pair(pair_id, num_changes=2):
    """Generates one previous/current SOW docx pair with `num_changes` edits.
    Returns the list of answer-key entries for the clauses that were changed."""
    all_clause_names = list(CLAUSE_BANK.keys())
    changed_clauses = random.sample(all_clause_names, min(num_changes, len(all_clause_names)))

    previous_doc = Document()
    current_doc = Document()
    previous_doc.add_heading(f'SOW Pair {pair_id} - Previous', level=1)
    current_doc.add_heading(f'SOW Pair {pair_id} - Current', level=1)

    answer_key = []

    for i, name in enumerate(all_clause_names, start=1):
        base_text = CLAUSE_BANK[name]["base"]
        previous_doc.add_heading(f"{i}. {name}", level=2)
        previous_doc.add_paragraph(base_text)

        current_doc.add_heading(f"{i}. {name}", level=2)

        if name in changed_clauses:
            new_text, risk, reason, rule = random.choice(CLAUSE_BANK[name]["variations"])
            current_doc.add_paragraph(new_text)
            answer_key.append({
                "pair_id": pair_id,
                "clause_id": str(i),
                "heading": name,
                "previous_text": base_text,
                "current_text": new_text,
                "risk_level": risk,
                "reason": reason,
                "policy_rule": rule
            })
        else:
            current_doc.add_paragraph(base_text)

    previous_doc.save(f'sow_pair{pair_id}_previous.docx')
    current_doc.save(f'sow_pair{pair_id}_current.docx')

    return answer_key


def export_policy_checklist():
    """Exports exactly 10 policy rules as a standalone, numbered file —
    separate from code, as required (T6: prompts/policy as versioned files,
    not pasted inside a node)."""
    rules = []
    for clause in CLAUSE_BANK.values():
        for _, _, _, rule in clause["variations"]:
            if rule not in rules:
                rules.append(rule)

    rules = sorted(set(rules))
    checklist = {
        "policy_checklist": [
            {"rule_id": i + 1, "rule": rule} for i, rule in enumerate(rules)
        ]
    }

    with open('policy_checklist.json', 'w') as f:
        json.dump(checklist, f, indent=2)

    print(f"Exported policy_checklist.json with {len(rules)} rules")
    return len(rules)


# ---------------------------------------------------------------------------
''' Generate 20 document pairs (2 changes each -> 40 labeled changes total),
  then deterministically select exactly 30 for the evaluation set (G5),
  and export exactly 10 policy rules (3.1 / T6). '''
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    all_answers = []
    for pid in range(1, 21):
        pair_answers = build_document_pair(pid, num_changes=2)
        all_answers.extend(pair_answers)
        print(f"Created pair {pid}: sow_pair{pid}_previous.docx / sow_pair{pid}_current.docx")

    # Save the full pool (40 entries) for reference / extra test data
    with open('answer_key_full.json', 'w') as f:
        json.dump(all_answers, f, indent=2)
    print(f"\nFull labeled change pool: {len(all_answers)} entries -> answer_key_full.json")

    # Deterministically select EXACTLY 30 for the evaluation set required by G5.
    # Same seed => same 30 every run, so this set is stable enough to be reviewed and "agreed" with Rajath, and reusable as a fixed benchmark.
    random.shuffle(all_answers)
    evaluation_set = all_answers[:30]
    assert len(evaluation_set) == 30, f"Expected exactly 30, got {len(evaluation_set)}"
    with open('evaluation_set_30.json', 'w') as f:
        json.dump(evaluation_set, f, indent=2)
    print(f"Evaluation set: exactly {len(evaluation_set)} entries -> evaluation_set_30.json")

    # Export the policy rules (doc requires "at least ten" — 3.1)
    num_rules = export_policy_checklist()
    assert num_rules >= 10, f"Expected at least 10 policy rules, got {num_rules}"

    print(f"\nDone. {num_rules} policy rules | {len(evaluation_set)}-clause evaluation set | 20 document pairs.")
    print("Re-running this script will always produce the SAME evaluation set and policy checklist (fixed seed).")