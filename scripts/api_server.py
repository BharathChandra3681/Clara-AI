"""
api_server.py
-------------
Lightweight local HTTP API server that n8n can call.
Bridges the n8n workflow to the Python extraction/patching logic.

Zero-cost: runs locally, no external services needed.

Start with:
    python api_server.py
    # Listens on http://localhost:5001

Endpoints:
    POST /extract  - Pipeline A: extract demo memo
    POST /patch    - Pipeline B: apply onboarding patch
    GET  /health   - Health check
    GET  /accounts - List all processed accounts
"""

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))

from run_demo import extract_memo_rule_based, patch_memo
from generate_agent_spec import build_agent_spec, save_agent_spec
from generate_changelog import deep_diff, render_markdown

OUTPUTS_DIR = Path(__file__).parent.parent / "outputs" / "accounts"

# Optionally use LLM if API key is present
USE_LLM = bool(os.environ.get("ANTHROPIC_API_KEY"))


class ClaraHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {format % args}")

    def send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        return json.loads(raw)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/health":
            self.send_json({"status": "ok", "llm_enabled": USE_LLM, "timestamp": datetime.now(timezone.utc).isoformat()})

        elif path == "/accounts":
            accounts = []
            if OUTPUTS_DIR.exists():
                for acc_dir in sorted(OUTPUTS_DIR.iterdir()):
                    if not acc_dir.is_dir():
                        continue
                    entry = {
                        "account_id": acc_dir.name,
                        "versions": [],
                        "has_changelog": (acc_dir / "changelog.json").exists()
                    }
                    for ver in ["v1", "v2"]:
                        ver_dir = acc_dir / ver
                        if ver_dir.exists():
                            memo_path = ver_dir / "account_memo.json"
                            spec_path = ver_dir / "agent_spec.json"
                            ver_entry = {"version": ver}
                            if memo_path.exists():
                                memo = json.loads(memo_path.read_text())
                                ver_entry["company_name"] = memo.get("company_name")
                                ver_entry["extracted_at"] = memo.get("extracted_at")
                            ver_entry["has_spec"] = spec_path.exists()
                            entry["versions"].append(ver_entry)
                    accounts.append(entry)
            self.send_json({"accounts": accounts, "total": len(accounts)})

        elif path.startswith("/accounts/") and path.endswith("/memo"):
            parts = path.split("/")
            if len(parts) >= 4:
                account_id = parts[2]
                version = parts[3] if len(parts) > 4 else "v2"
                memo_path = OUTPUTS_DIR / account_id / version / "account_memo.json"
                if memo_path.exists():
                    self.send_json(json.loads(memo_path.read_text()))
                else:
                    self.send_json({"error": f"Not found: {account_id}/{version}"}, 404)

        else:
            self.send_json({"error": "Not found", "path": path}, 404)

    def do_POST(self):
        path = urlparse(self.path).path

        try:
            body = self.read_json_body()
        except Exception as e:
            self.send_json({"error": f"Invalid JSON body: {e}"}, 400)
            return

        try:
            if path == "/extract":
                account_id = body.get("account_id")
                transcript = body.get("transcript", "")
                if not account_id or not transcript:
                    self.send_json({"error": "account_id and transcript required"}, 400)
                    return

                if USE_LLM:
                    from extract_account_memo import extract_demo
                    memo = extract_demo(transcript, account_id)
                else:
                    memo = extract_memo_rule_based(transcript, account_id, "demo")

                # Save
                out_dir = OUTPUTS_DIR / account_id / "v1"
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "account_memo.json").write_text(json.dumps(memo, indent=2))
                spec = build_agent_spec(memo, "v1")
                save_agent_spec(spec, account_id, "v1")

                self.send_json({"success": True, "memo": memo, "agent_spec": spec})

            elif path == "/patch":
                account_id = body.get("account_id")
                transcript = body.get("transcript", "")
                existing_memo = body.get("existing_memo")
                if isinstance(existing_memo, str):
                    existing_memo = json.loads(existing_memo)

                if not account_id or not transcript:
                    self.send_json({"error": "account_id and transcript required"}, 400)
                    return

                if not existing_memo:
                    memo_path = OUTPUTS_DIR / account_id / "v1" / "account_memo.json"
                    if not memo_path.exists():
                        self.send_json({"error": f"v1 memo not found for {account_id}"}, 404)
                        return
                    existing_memo = json.loads(memo_path.read_text())

                if USE_LLM:
                    from extract_account_memo import extract_onboarding_patch
                    updated_memo, changes = extract_onboarding_patch(transcript, account_id, existing_memo)
                else:
                    updated_memo, changes = patch_memo(existing_memo, transcript, account_id)

                # Save
                out_dir = OUTPUTS_DIR / account_id / "v2"
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "account_memo.json").write_text(json.dumps(updated_memo, indent=2))
                spec_v2 = build_agent_spec(updated_memo, "v2")
                save_agent_spec(spec_v2, account_id, "v2")

                # Changelog
                diff_changes = deep_diff(existing_memo, updated_memo)
                account_dir = OUTPUTS_DIR / account_id
                changelog = {
                    "account_id": account_id,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "from_version": "v1", "to_version": "v2",
                    "total_changes": len(diff_changes), "changes": diff_changes
                }
                (account_dir / "changelog.json").write_text(json.dumps(changelog, indent=2))
                md = render_markdown(account_id, diff_changes, existing_memo, updated_memo)
                (account_dir / "changelog.md").write_text(md)

                self.send_json({
                    "success": True,
                    "updated_memo": updated_memo,
                    "agent_spec": spec_v2,
                    "changes": changes,
                    "diff_count": len(diff_changes)
                })

            else:
                self.send_json({"error": "Unknown endpoint"}, 404)

        except Exception as e:
            self.send_json({
                "error": str(e),
                "traceback": traceback.format_exc()
            }, 500)


def run(port: int = 5001):
    server = HTTPServer(("0.0.0.0", port), ClaraHandler)
    llm_status = "LLM enabled (Anthropic)" if USE_LLM else "rule-based extraction (zero-cost)"
    print(f"🚀 Clara API Server running on http://localhost:{port}")
    print(f"   Mode: {llm_status}")
    print(f"   Endpoints: GET /health, GET /accounts, POST /extract, POST /patch")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[stop] Server stopped.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5001)
    args = parser.parse_args()
    run(args.port)
