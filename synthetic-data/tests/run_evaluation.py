import sys
import argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from paths import EVALUATION_SET_PATH, OUTPUTS_DIR
from classify_clauses import classify_clause
import json

parser = argparse.ArgumentParser(description="Run the 30-clause evaluation set against a prompt version.")
parser.add_argument("--prompt", default="classify_v1", help="Prompt version file name in prompts/ (without .txt)")
parser.add_argument("--runs", type=int, default=1, help="How many times to repeat the full evaluation")
args = parser.parse_args()

with open(EVALUATION_SET_PATH, "r") as f:
    evaluation_set = json.load(f)

print(f"\nPrompt version: {args.prompt} | Runs: {args.runs} | Cases: {len(evaluation_set)}\n")

all_runs = []
for run_no in range(1, args.runs + 1):
    results = []
    correct = 0
    for i, entry in enumerate(evaluation_set, start=1):
        print(f"[run {run_no}/{args.runs}] case {i}/{len(evaluation_set)}: {entry['heading']} (pair {entry['pair_id']})")
        prediction = classify_clause(
            entry["heading"],
            entry["previous_text"],
            entry["current_text"],
            prompt_version=args.prompt,
        )
        predicted = prediction.get("risk_level", "Error")
        actual = entry["risk_level"]
        match = (predicted == actual)
        correct += match
        results.append({
            "pair_id": entry["pair_id"],
            "heading": entry["heading"],
            "actual_risk_level": actual,
            "predicted_risk_level": predicted,
            "match": match,
            "predicted_reason": prediction.get("reason", ""),
            "predicted_policy_rule": prediction.get("policy_rule_touched", ""),
        })
    accuracy = correct / len(evaluation_set) * 100
    all_runs.append({"run": run_no, "correct": correct, "accuracy_percent": round(accuracy, 1), "results": results})

# Summary
print("\n" + "=" * 50)
print(f"SUMMARY  prompt={args.prompt}")
print("=" * 50)
for r in all_runs:
    print(f"Run {r['run']}: {r['correct']}/{len(evaluation_set)} = {r['accuracy_percent']}%")

mean_acc = sum(r["accuracy_percent"] for r in all_runs) / len(all_runs)
print(f"Mean accuracy: {mean_acc:.1f}%")

flips = 0
if len(all_runs) > 1:
    for idx in range(len(evaluation_set)):
        labels = {r["results"][idx]["predicted_risk_level"] for r in all_runs}
        if len(labels) > 1:
            flips += 1
    print(f"Cases whose predicted label changed between runs: {flips}/{len(evaluation_set)}")

output_path = OUTPUTS_DIR / f"evaluation_{args.prompt}.json"
with open(output_path, "w") as f:
    json.dump({
        "prompt_version": args.prompt,
        "runs": args.runs,
        "mean_accuracy_percent": round(mean_acc, 1),
        "cases_with_label_changes": flips,
        "all_runs": all_runs,
    }, f, indent=2)
print(f"\nSaved to {output_path}")