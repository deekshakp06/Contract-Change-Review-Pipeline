import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paths import EVALUATION_SET_PATH, OUTPUTS_DIR

VERSIONS = ["classify_v1", "classify_v2_weak"]  # edit to compare other versions


def norm_rule(s):
    s = (s or "").strip().lower().rstrip(".")
    if s.startswith("none") or s in ("", "n/a"):
        return "none"
    return s


def rule_match(expected, predicted):
    e, p = norm_rule(expected), norm_rule(predicted)
    if e == "none" or p == "none":
        return e == p
    return e == p or e in p or p in e


with open(EVALUATION_SET_PATH, "r") as f:
    cases = json.load(f)

summary = {}
per_case_risk = {}

for v in VERSIONS:
    path = OUTPUTS_DIR / f"evaluation_{v}.json"
    with open(path, "r") as f:
        data = json.load(f)
    runs = data["all_runs"]
    n = len(cases)

    risk_scores, rule_scores = [], []
    per_case = [0] * n
    for run in runs:
        risk_ok = 0
        rule_ok = 0
        for i, r in enumerate(run["results"]):
            if r["match"]:
                risk_ok += 1
                per_case[i] += 1
            if rule_match(cases[i].get("policy_rule"), r.get("predicted_policy_rule")):
                rule_ok += 1
        risk_scores.append(risk_ok / n * 100)
        rule_scores.append(rule_ok / n * 100)

    summary[v] = {
        "runs": len(runs),
        "risk_mean": sum(risk_scores) / len(risk_scores),
        "rule_mean": sum(rule_scores) / len(rule_scores),
    }
    per_case_risk[v] = per_case

print("\n" + "=" * 60)
print("PROMPT COMPARISON (from saved runs, no API calls)")
print("=" * 60)
for v, s in summary.items():
    print(f"{v:20s} runs={s['runs']}  risk-level accuracy={s['risk_mean']:.1f}%  policy-rule match={s['rule_mean']:.1f}%")

a, b = VERSIONS[0], VERSIONS[1]
runs_a, runs_b = summary[a]["runs"], summary[b]["runs"]
print(f"\nCases where the two versions differ on risk level (runs correct out of {runs_a}/{runs_b}):")
diffs = 0
for i, c in enumerate(cases):
    ca, cb = per_case_risk[a][i], per_case_risk[b][i]
    if ca != cb:
        diffs += 1
        print(f"  {c['heading']} (pair {c['pair_id']}), label={c['risk_level']}: {a}={ca}/{runs_a}  {b}={cb}/{runs_b}")
if diffs == 0:
    print("  none")