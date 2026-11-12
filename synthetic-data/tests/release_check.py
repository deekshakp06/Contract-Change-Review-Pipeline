import sys
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paths import EVALUATION_SET_PATH, OUTPUTS_DIR

# Differences smaller than this (in percentage points) are treated as run-to-run noise.
# Measured noise for classify_v1 was roughly 1-2 cases out of 30 (3-7 points). Rajath to confirm.
NOISE_MARGIN = 3.0

parser = argparse.ArgumentParser(description="Prompt release check (G8): block a candidate prompt that is weaker than the live one.")
parser.add_argument("--live", default="classify_v1")
parser.add_argument("--candidate", required=True)
args = parser.parse_args()


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
n = len(cases)


def score(version):
    with open(OUTPUTS_DIR / f"evaluation_{version}.json", "r") as f:
        runs = json.load(f)["all_runs"]
    risk, rule = [], []
    per_case_correct = [0] * n
    for run in runs:
        r_ok = u_ok = 0
        for i, r in enumerate(run["results"]):
            if r["match"]:
                r_ok += 1
                per_case_correct[i] += 1
            if rule_match(cases[i].get("policy_rule"), r.get("predicted_policy_rule")):
                u_ok += 1
        risk.append(r_ok / n * 100)
        rule.append(u_ok / n * 100)
    return {
        "runs": len(runs),
        "risk": sum(risk) / len(risk),
        "rule": sum(rule) / len(rule),
        "per_case": per_case_correct,
    }


live = score(args.live)
cand = score(args.candidate)

reasons = []
if cand["risk"] < live["risk"] - NOISE_MARGIN:
    reasons.append(f"risk-level accuracy lower: {cand['risk']:.1f}% vs live {live['risk']:.1f}%")
if cand["rule"] < live["rule"] - NOISE_MARGIN:
    reasons.append(f"policy-rule match lower: {cand['rule']:.1f}% vs live {live['rule']:.1f}%")

# Regression: a case the live prompt got right in every run, but the candidate never got right.
regressions = [
    cases[i] for i in range(n)
    if live["per_case"][i] == live["runs"] and cand["per_case"][i] == 0
]
if regressions:
    reasons.append(f"{len(regressions)} stable case(s) regressed (live right every run, candidate never)")

decision = "BLOCK" if reasons else "PASS"

print("\n" + "=" * 60)
print(f"RELEASE CHECK  live={args.live}  candidate={args.candidate}")
print("=" * 60)
print(f"{'':18s}{'risk accuracy':>16s}{'rule match':>14s}{'runs':>7s}")
print(f"{args.live:18s}{live['risk']:>15.1f}%{live['rule']:>13.1f}%{live['runs']:>7d}")
print(f"{args.candidate:18s}{cand['risk']:>15.1f}%{cand['rule']:>13.1f}%{cand['runs']:>7d}")
print(f"(differences under {NOISE_MARGIN} points are treated as noise)\n")
for c in regressions:
    print(f"  regression: {c['heading']} (pair {c['pair_id']}), label={c['risk_level']}")
print(f"\nDECISION: {decision}")
for r in reasons:
    print(f"  - {r}")

# Log every check, including blocked releases and the scores behind them (doc section 11.1)
entry = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "live": args.live,
    "candidate": args.candidate,
    "live_scores": {"risk": round(live["risk"], 1), "rule": round(live["rule"], 1), "runs": live["runs"]},
    "candidate_scores": {"risk": round(cand["risk"], 1), "rule": round(cand["rule"], 1), "runs": cand["runs"]},
    "regressions": [f"{c['heading']} (pair {c['pair_id']})" for c in regressions],
    "decision": decision,
    "reasons": reasons,
}
with open(OUTPUTS_DIR / "release_log.jsonl", "a") as f:
    f.write(json.dumps(entry) + "\n")

sys.exit(1 if decision == "BLOCK" else 0)