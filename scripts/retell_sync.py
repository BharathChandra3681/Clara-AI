"""
retell_sync.py
--------------
Syncs generated agent specs to Retell AI via their API.
Uses only free-tier API — no paid plan required (just the $10 free credits).

Usage:
    # Set your API key first
    export RETELL_API_KEY=key_xxxxxxxxxxxxxxxx

    # Push a single account's v1 agent
    python retell_sync.py --account_id ACC001 --version v1

    # Push all accounts' v2 agents
    python retell_sync.py --all --version v2

    # Dry run (shows what would be sent, doesn't call API)
    python retell_sync.py --all --version v2 --dry-run
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

OUTPUTS_DIR = Path(__file__).parent.parent / "outputs" / "accounts"
RETELL_BASE  = "https://api.retellai.com"

# ── Retell API helpers ─────────────────────────────────────────────────────────

def retell_request(method: str, path: str, body: dict = None) -> dict:
    api_key = os.environ.get("RETELL_API_KEY", "")
    if not api_key:
        raise EnvironmentError("RETELL_API_KEY not set. Export it before running.")

    url = f"{RETELL_BASE}{path}"
    data = json.dumps(body).encode() if body else None

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        raise RuntimeError(f"Retell API error {e.code}: {error_body}")


def create_llm(system_prompt: str, account_id: str) -> str:
    """Create a Retell LLM config and return its llm_id."""
    payload = {
        "model": "gemini-2.0-flash",     # free via Google AI Studio
        "general_prompt": system_prompt,
        "general_tools": [
            {
                "type": "end_call",
                "name": "end_call",
                "description": "End the call after completing all tasks and confirming no further assistance is needed."
            }
        ],
    }
    result = retell_request("POST", "/create-retell-llm", payload)
    return result["llm_id"]


def create_agent(llm_id: str, spec: dict) -> dict:
    """Create a Retell agent and return the full response."""
    kv = spec.get("key_variables", {})
    payload = {
        "agent_name": spec.get("agent_name", "Clara Agent"),
        "voice_id": "retell-Cimo",           # built-in Retell voice (always available)
        "language": "en-US",
        "response_engine": {
            "type": "retell-llm",
            "llm_id": llm_id,
        },
        "voice_speed": 1.0,
        "voice_temperature": 0.7,
        "responsiveness": 1.0,
        "enable_backchannel": True,
        "reminder_trigger_ms": 10000,
        "reminder_max_count": 1,
    }
    return retell_request("POST", "/create-agent", payload)


def update_agent(agent_id: str, llm_id: str, spec: dict) -> dict:
    """Update an existing Retell agent."""
    payload = {
        "agent_name": spec.get("agent_name"),
        "voice_id": "retell-Cimo",
        "response_engine": {
            "type": "retell-llm",
            "llm_id": llm_id,
        },
    }
    return retell_request("PATCH", f"/update-agent/{agent_id}", payload)


def list_agents() -> list:
    return retell_request("GET", "/list-agents")


# ── Registry: track account_id → retell agent_id ──────────────────────────────

REGISTRY_PATH = Path(__file__).parent.parent / "outputs" / "retell_registry.json"

def load_registry() -> dict:
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text())
    return {}

def save_registry(registry: dict):
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2))


# ── Main sync logic ────────────────────────────────────────────────────────────

def sync_account(account_id: str, version: str, dry_run: bool = False) -> dict:
    spec_path = OUTPUTS_DIR / account_id / version / "agent_spec.json"
    if not spec_path.exists():
        print(f"[{account_id}] ❌ No agent spec found at {spec_path}")
        return {"status": "error", "reason": "spec_not_found"}

    spec = json.loads(spec_path.read_text())
    system_prompt = spec.get("system_prompt", "")
    agent_name = spec.get("agent_name", account_id)

    print(f"[{account_id}] Syncing '{agent_name}' ({version}) to Retell...")

    if dry_run:
        print(f"[{account_id}] 🔍 DRY RUN — would send:")
        print(f"           Agent name  : {agent_name}")
        print(f"           Prompt chars: {len(system_prompt)}")
        print(f"           Timeout     : {spec.get('call_transfer_protocol', {}).get('timeout_seconds')}s")
        return {"status": "dry_run"}

    registry = load_registry()
    reg_key = f"{account_id}"

    try:
        # Step 1: Create or update LLM
        print(f"[{account_id}]   Creating LLM config...")
        llm_id = create_llm(system_prompt, account_id)
        print(f"[{account_id}]   LLM created: {llm_id}")

        # Step 2: Create or update Agent
        existing_agent_id = registry.get(reg_key, {}).get("agent_id")

        if existing_agent_id:
            print(f"[{account_id}]   Updating existing agent: {existing_agent_id}")
            result = update_agent(existing_agent_id, llm_id, spec)
            agent_id = existing_agent_id
            action = "updated"
        else:
            print(f"[{account_id}]   Creating new agent...")
            result = create_agent(llm_id, spec)
            agent_id = result["agent_id"]
            action = "created"

        # Step 3: Save to registry
        registry[reg_key] = {
            "account_id": account_id,
            "agent_id": agent_id,
            "llm_id": llm_id,
            "version": version,
            "agent_name": agent_name,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }
        save_registry(registry)

        print(f"[{account_id}] ✅ Agent {action}: {agent_id}")
        print(f"[{account_id}]    View at: https://beta.retellai.com/agent/{agent_id}")
        return {"status": "success", "agent_id": agent_id, "action": action}

    except Exception as e:
        print(f"[{account_id}] ❌ Failed: {e}")
        return {"status": "error", "reason": str(e)}


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Clara AI – Retell Sync")
    parser.add_argument("--account_id", help="Single account ID to sync")
    parser.add_argument("--all", action="store_true", help="Sync all accounts")
    parser.add_argument("--version", default="v2", choices=["v1", "v2"])
    parser.add_argument("--dry-run", action="store_true", help="Preview without calling API")
    args = parser.parse_args()

    if not args.account_id and not args.all:
        print("Specify --account_id ACC001 or --all")
        sys.exit(1)

    if args.dry_run:
        print("🔍 DRY RUN MODE — no API calls will be made\n")

    accounts = []
    if args.all:
        accounts = [d.name for d in sorted(OUTPUTS_DIR.iterdir()) if d.is_dir()]
    else:
        accounts = [args.account_id]

    results = []
    for acc in accounts:
        r = sync_account(acc, args.version, dry_run=args.dry_run)
        results.append({"account_id": acc, **r})

    print(f"\n{'='*50}")
    print(f"  Synced: {sum(1 for r in results if r.get('status') == 'success')}/{len(results)}")
    if not args.dry_run:
        registry = load_registry()
        print(f"\n  Retell Agent IDs:")
        for acc in accounts:
            entry = registry.get(acc, {})
            if entry.get("agent_id"):
                print(f"    {acc}: {entry['agent_id']}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()