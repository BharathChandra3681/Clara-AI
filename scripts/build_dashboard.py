"""
build_dashboard.py
------------------
Generates a static HTML dashboard from the pipeline outputs.
No server needed — opens directly in browser.

Usage:
    python build_dashboard.py
    # Outputs: outputs/dashboard.html
"""

import json
from pathlib import Path
from datetime import datetime, timezone

OUTPUTS_DIR   = Path(__file__).parent.parent / "outputs" / "accounts"
TEMPLATE_PATH = Path(__file__).parent / "dashboard_template.html"
OUTPUT_PATH   = Path(__file__).parent.parent / "outputs" / "dashboard.html"


def load_account_data() -> list[dict]:
    accounts = []
    if not OUTPUTS_DIR.exists():
        return accounts

    for acc_dir in sorted(OUTPUTS_DIR.iterdir()):
        if not acc_dir.is_dir():
            continue

        entry = {
            "account_id": acc_dir.name,
            "versions": [],
            "has_changelog": False,
            "v1_memo": None,
            "v2_memo": None,
            "v1_spec": None,
            "v2_spec": None,
            "changelog": None,
        }

        for ver in ["v1", "v2"]:
            ver_dir = acc_dir / ver
            if not ver_dir.exists():
                continue

            ver_info = {"version": ver}
            memo_path = ver_dir / "account_memo.json"
            spec_path = ver_dir / "agent_spec.json"

            if memo_path.exists():
                memo = json.loads(memo_path.read_text())
                ver_info["company_name"] = memo.get("company_name")
                ver_info["extracted_at"] = memo.get("extracted_at")
                entry[f"{ver}_memo"] = memo

            if spec_path.exists():
                spec = json.loads(spec_path.read_text())
                entry[f"{ver}_spec"] = spec
                ver_info["has_spec"] = True

            entry["versions"].append(ver_info)

        # Load changelog
        for name in ["changelog.json"]:
            cl_path = acc_dir / name
            if cl_path.exists():
                entry["changelog"] = json.loads(cl_path.read_text())
                entry["has_changelog"] = True
                break

        accounts.append(entry)

    return accounts


def build_dashboard():
    print("[dashboard] Loading account data...")
    accounts = load_account_data()
    print(f"[dashboard] Found {len(accounts)} accounts")

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    accounts_json = json.dumps(accounts, indent=2, default=str)

    # Inject data
    html = template.replace("const ACCOUNTS_DATA = __ACCOUNTS_JSON__;",
                             f"const ACCOUNTS_DATA = {accounts_json};")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"[dashboard] ✅ Dashboard saved: {OUTPUT_PATH}")
    print(f"[dashboard]    Open in browser: file://{OUTPUT_PATH.resolve()}")
    return OUTPUT_PATH


if __name__ == "__main__":
    build_dashboard()
