"""
generate_changelog.py
----------------------
Generates a human-readable changelog (changes.md) and structured diff (changes.json)
by comparing v1 and v2 Account Memos and Agent Specs.

Usage:
    python generate_changelog.py --account_id ACC001
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

OUTPUTS_DIR = Path(__file__).parent.parent / "outputs" / "accounts"


# ── Deep diff ──────────────────────────────────────────────────────────────────

def deep_diff(old: object, new: object, path: str = "") -> list[dict]:
    """Recursively diff two objects, returning a list of change records."""
    changes = []

    if isinstance(old, dict) and isinstance(new, dict):
        all_keys = set(old.keys()) | set(new.keys())
        for key in sorted(all_keys):
            child_path = f"{path}.{key}" if path else key
            if key not in old:
                changes.append({
                    "field": child_path,
                    "old_value": None,
                    "new_value": new[key],
                    "change_type": "added"
                })
            elif key not in new:
                changes.append({
                    "field": child_path,
                    "old_value": old[key],
                    "new_value": None,
                    "change_type": "removed"
                })
            else:
                changes.extend(deep_diff(old[key], new[key], child_path))

    elif isinstance(old, list) and isinstance(new, list):
        if old != new:
            changes.append({
                "field": path,
                "old_value": old,
                "new_value": new,
                "change_type": "modified"
            })

    else:
        # Skip metadata-only fields
        skip_fields = {"extracted_at", "generated_at", "version", "extraction_stage"}
        field_name = path.split(".")[-1]
        if field_name not in skip_fields and old != new:
            changes.append({
                "field": path,
                "old_value": old,
                "new_value": new,
                "change_type": "modified"
            })

    return changes


# ── Markdown renderer ──────────────────────────────────────────────────────────

def render_markdown(account_id: str, changes: list[dict], memo_v1: dict, memo_v2: dict) -> str:
    company = memo_v2.get("company_name") or account_id
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# Changelog: {company} ({account_id})",
        f"",
        f"**Generated:** {ts}  ",
        f"**Change:** v1 (Demo-derived) → v2 (Onboarding-confirmed)",
        f"",
        f"---",
        f"",
        f"## Summary",
        f"",
        f"- **Total changes:** {len(changes)}",
        f"- **Added fields:** {sum(1 for c in changes if c['change_type'] == 'added')}",
        f"- **Modified fields:** {sum(1 for c in changes if c['change_type'] == 'modified')}",
        f"- **Removed fields:** {sum(1 for c in changes if c['change_type'] == 'removed')}",
        f"",
        f"---",
        f"",
        f"## Field-Level Changes",
        f"",
    ]

    if not changes:
        lines.append("_No changes detected between v1 and v2._")
    else:
        for c in changes:
            change_type = c["change_type"].upper()
            field = c["field"]
            old_val = json.dumps(c["old_value"]) if c["old_value"] is not None else "_null_"
            new_val = json.dumps(c["new_value"]) if c["new_value"] is not None else "_null_"

            lines.append(f"### `{field}` [{change_type}]")
            if c["change_type"] == "added":
                lines.append(f"- **Added:** `{new_val}`")
            elif c["change_type"] == "removed":
                lines.append(f"- **Removed:** was `{old_val}`")
            else:
                lines.append(f"- **Before:** `{old_val}`")
                lines.append(f"- **After:**  `{new_val}`")
            lines.append("")

    lines += [
        "---",
        "",
        "## Version Notes",
        "",
        "| Version | Source | Purpose |",
        "|---------|--------|---------|",
        "| v1 | Demo call | Directional assumptions, preliminary configuration |",
        "| v2 | Onboarding call | Confirmed operational rules, production-ready |",
        "",
        "_v2 is the authoritative configuration for production deployment._",
    ]

    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Clara Answers – Changelog Generator")
    parser.add_argument("--account_id", required=True)
    args = parser.parse_args()

    account_dir = OUTPUTS_DIR / args.account_id

    # Load v1 and v2 memos
    v1_memo_path = account_dir / "v1" / "account_memo.json"
    v2_memo_path = account_dir / "v2" / "account_memo.json"

    if not v1_memo_path.exists():
        print(f"ERROR: v1 memo not found at {v1_memo_path}")
        raise SystemExit(1)
    if not v2_memo_path.exists():
        print(f"ERROR: v2 memo not found at {v2_memo_path}")
        raise SystemExit(1)

    memo_v1 = json.loads(v1_memo_path.read_text())
    memo_v2 = json.loads(v2_memo_path.read_text())

    # Compute diff
    changes = deep_diff(memo_v1, memo_v2)

    # Save JSON changelog
    changelog_json = {
        "account_id": args.account_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "from_version": "v1",
        "to_version": "v2",
        "total_changes": len(changes),
        "changes": changes
    }
    json_path = account_dir / "changelog.json"
    json_path.write_text(json.dumps(changelog_json, indent=2))
    print(f"[save] Changelog JSON: {json_path}")

    # Save Markdown changelog
    md = render_markdown(args.account_id, changes, memo_v1, memo_v2)
    md_path = account_dir / "changelog.md"
    md_path.write_text(md)
    print(f"[save] Changelog MD:   {md_path}")

    print(f"\n✅ Changelog generated for {args.account_id}: {len(changes)} changes")


if __name__ == "__main__":
    main()
