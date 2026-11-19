"""Send sow_pair1..20 through the n8n webhook one after another and time each.
Usage (PowerShell, from the synthetic-data folder):
    $env:N8N_WEBHOOK_URL = "http://localhost:5678/webhook/contract-pair"
    $env:N8N_WEBHOOK_SECRET = "<your webhook secret>"
    python tests\\run_volume.py
"""
import json, os, subprocess, sys, time
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "data" / "sow_documents"
url = os.environ.get("N8N_WEBHOOK_URL")
secret = os.environ.get("N8N_WEBHOOK_SECRET")
if not url or not secret:
    sys.exit("Set N8N_WEBHOOK_URL and N8N_WEBHOOK_SECRET first.")

curl = "curl.exe" if os.name == "nt" else "curl"
t_all = time.time()
for i in range(1, 21):
    prev = DOCS / f"sow_pair{i}_previous.docx"
    cur = DOCS / f"sow_pair{i}_current.docx"
    t0 = time.time()
    p = subprocess.run(
        [curl, "-s", "-m", "600", "-X", "POST", url,
         "-H", "X-Webhook-Secret: " + secret,
         "-F", "previous_file=@" + str(prev),
         "-F", "current_file=@" + str(cur)],
        capture_output=True, text=True, encoding="utf-8")
    secs = time.time() - t0
    status = "no JSON"
    try:
        d = json.loads(p.stdout)
        d = d[0] if isinstance(d, list) and d else d
        status = str(d.get("status", "ok")) if isinstance(d, dict) else "ok"
    except Exception:
        pass
    print(f"pair{i:>2}: {secs:6.1f}s  {status}")
print(f"TOTAL: {time.time() - t_all:.1f}s for 20 pairs")