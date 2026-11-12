import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paths import POLICY_CHECKLIST_PATH, SOW_DIR, OUTPUTS_DIR, PROMPTS_DIR
from compare_clauses import compare_versions
from openai import OpenAI
import os
import json
import time
from dotenv import load_dotenv

# Load AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT and proxy settings from the .env file in the
# project root, so they don't need to be re-typed into every new terminal.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

print("Script started...")

ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
DEPLOYMENT_NAME = "gpt-5.1"

# Route through the local PX proxy manager (handles corporate proxy auth for
# us), if HTTP_PROXY/HTTPS_PROXY are set in .env. Falls back to no proxy if
# not set, so this is safe to leave in even if PX isn't running.
import httpx
proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
http_client = httpx.Client(proxy=proxy_url) if proxy_url else None

client = OpenAI(
    base_url=ENDPOINT,
    api_key=os.environ["AZURE_OPENAI_KEY"],
    timeout=20.0,  # fail fast instead of hanging forever
    http_client=http_client
)

print("Client created...")

with open(POLICY_CHECKLIST_PATH, "r") as f:
    POLICY_CHECKLIST = json.load(f)["policy_checklist"]

POLICY_TEXT = "\n".join(f"{r['rule_id']}. {r['rule']}" for r in POLICY_CHECKLIST)

# Prompts live in versioned files in prompts/, not inside the code (T6).
PROMPT_VERSION = "classify_v1"  # default (live) version
_PROMPT_CACHE = {}


def load_prompt(version):
    """Loads a prompt template from prompts/<version>.txt (cached)."""
    if version not in _PROMPT_CACHE:
        with open(PROMPTS_DIR / f"{version}.txt", "r", encoding="utf-8") as f:
            _PROMPT_CACHE[version] = f.read()
    return _PROMPT_CACHE[version]


print(f"Policy checklist loaded. Prompt version: {PROMPT_VERSION}. About to classify...")


def classify_clause(heading, previous_text, current_text, prompt_version=PROMPT_VERSION):
    """Calls the Azure-hosted GPT-5.1 endpoint (Responses API) to classify one changed clause.
    The result includes a 'usage' entry with input/output tokens and latency (G3)."""
    prompt = load_prompt(prompt_version).format(
        POLICY_TEXT=POLICY_TEXT,
        heading=heading,
        previous_text=previous_text,
        current_text=current_text,
    )

    print(f"Calling API for clause: {heading}...")

    start = time.time()
    try:
        response = client.responses.create(
            model=DEPLOYMENT_NAME,
            input=prompt,
        )
        latency_ms = int((time.time() - start) * 1000)
        print("API call succeeded.")
    except Exception as e:
        print(f"API CALL FAILED: {type(e).__name__}: {e}")
        return {
            "risk_level": "Error",
            "reason": f"API call failed: {e}",
            "policy_rule_touched": "N/A",
            "usage": {"input_tokens": None, "output_tokens": None,
                      "latency_ms": int((time.time() - start) * 1000)},
        }

    usage = getattr(response, "usage", None)
    usage_info = {
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "latency_ms": latency_ms,
    }

    raw_output = response.output[0].content[0].text.strip()
    raw_output = raw_output.replace("```json", "").replace("```", "").strip()

    try:
        result = json.loads(raw_output)
    except json.JSONDecodeError:
        result = {
            "risk_level": "Unknown",
            "reason": f"Could not parse model response: {raw_output[:100]}",
            "policy_rule_touched": "N/A"
        }

    # C6 guard: the model must classify only, never rewrite/reword clause text.
    reason_text = result.get("reason", "")
    if len(reason_text) > 200:
        result["c6_warning"] = "Reason field unusually long — possible clause rewrite, review manually."
    elif current_text and len(current_text) > 20 and current_text.strip().lower() in reason_text.strip().lower():
        result["c6_warning"] = "Reason field contains the full current clause text — possible rewrite, review manually."

    result["usage"] = usage_info
    return result


def run_pipeline(previous_path, current_path):
    """Full mini-pipeline: extract -> compare -> classify changed clauses only."""
    comparison_results = compare_versions(previous_path, current_path)

    review_pack = []

    for clause in comparison_results:
        if clause["status"] == "unchanged":
            continue  # C3: unchanged clauses must never cost a token — skip entirely

        classification = classify_clause(
            clause["heading"],
            clause["previous_text"],
            clause["current_text"]
        )

        review_pack.append({
            "heading": clause["heading"],
            "status": clause["status"],
            "previous_text": clause["previous_text"],
            "current_text": clause["current_text"],
            "risk_level": classification["risk_level"],
            "reason": classification["reason"],
            "policy_rule_touched": classification["policy_rule_touched"],
            "usage": classification.get("usage"),
        })

    return review_pack


if __name__ == "__main__":
    pack = run_pipeline(
        str(SOW_DIR / "sow_pair1_previous.docx"),
        str(SOW_DIR / "sow_pair1_current.docx")
    )

    print(f"Review pack generated with {len(pack)} changed clause(s):\n")
    for item in pack:
        u = item.get("usage") or {}
        print(f"[{item['risk_level']}] {item['heading']}")
        print(f"  Reason: {item['reason']}")
        print(f"  Tokens in/out: {u.get('input_tokens')}/{u.get('output_tokens')}   Latency: {u.get('latency_ms')} ms\n")

    output_path = OUTPUTS_DIR / "review_pack_pair1.json"
    with open(output_path, "w") as f:
        json.dump(pack, f, indent=2)
    print(f"Saved full review pack to {output_path}")