"""
run_pipeline.py
---------------
Batch runner for the full Clara Answers pipeline.

Pipeline A (Demo):
  transcript -> extract_account_memo (v1) -> generate_agent_spec (v1)

Pipeline B (Onboarding):
  transcript + v1_memo -> extract_account_memo (v2) -> generate_agent_spec (v2) -> generate_changelog

Usage:
    # Run all accounts
    python run_pipeline.py --dataset_dir ./dataset

    # Run single account
    python run_pipeline.py --dataset_dir ./dataset --account_id ACC001

    # Re-run (idempotent - overwrites existing outputs)
    python run_pipeline.py --dataset_dir ./dataset --force

Dataset directory structure expected:
    dataset/
        ACC001/
            demo_transcript.txt
            onboarding_transcript.txt   (optional - only needed for Pipeline B)
        ACC002/
            demo_transcript.txt
            onboarding_transcript.txt
        ...

    OR with a manifest file:
    dataset/manifest.json:
    [
        {
            "account_id": "ACC001",
            "demo_transcript": "path/to/demo.txt",
            "onboarding_transcript": "path/to/onboarding.txt"   // optional
        }
    ]
"""

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Add scripts dir to path
sys.path.insert(0, str(Path(__file__).parent))

from extract_account_memo import extract_demo, extract_onboarding_patch, save_memo, save_changelog
from generate_agent_spec import build_agent_spec, save_agent_spec
from generate_changelog import deep_diff, render_markdown

OUTPUTS_DIR = Path(__file__).parent.parent / "outputs" / "accounts"
LOGS_DIR    = Path(__file__).parent.parent / "outputs" / "logs"


# ── Logging ───────────────────────────────────────────────────────────────────

def log(msg: str, level: str = "INFO"):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    prefix = {"INFO": "✅", "WARN": "⚠️ ", "ERROR": "❌", "START": "🚀"}.get(level, "  ")
    print(f"[{ts}] {prefix} {msg}")


# ── Account discovery ─────────────────────────────────────────────────────────

def discover_accounts(dataset_dir: Path) -> list[dict]:
    """
    Discover accounts from dataset directory.
    Supports manifest.json or auto-discovery from subdirectories.
    """
    manifest_path = dataset_dir / "manifest.json"
    if manifest_path.exists():
        log(f"Loading manifest: {manifest_path}")
        entries = json.loads(manifest_path.read_text())
        # Resolve relative paths
        for e in entries:
            for key in ["demo_transcript", "onboarding_transcript"]:
                if key in e and e[key] and not Path(e[key]).is_absolute():
                    e[key] = str(dataset_dir / e[key])
        return entries

    # Auto-discover subdirectories
    accounts = []
    for subdir in sorted(dataset_dir.iterdir()):
        if not subdir.is_dir():
            continue
        account_id = subdir.name

        # Find demo transcript (flexible naming)
        demo = None
        for name in ["demo_transcript.txt", "demo.txt", "transcript_demo.txt"]:
            if (subdir / name).exists():
                demo = str(subdir / name)
                break

        # Find onboarding transcript (flexible naming)
        onboarding = None
        for name in ["onboarding_transcript.txt", "onboarding.txt", "transcript_onboarding.txt"]:
            if (subdir / name).exists():
                onboarding = str(subdir / name)
                break

        if demo:
            accounts.append({
                "account_id": account_id,
                "demo_transcript": demo,
                "onboarding_transcript": onboarding,
            })
        else:
            log(f"Skipping {account_id}: no demo transcript found", "WARN")

    return accounts


# ── Single account pipeline ────────────────────────────────────────────────────

def run_account(entry: dict, force: bool = False) -> dict:
    account_id  = entry["account_id"]
    demo_path   = entry.get("demo_transcript")
    ob_path     = entry.get("onboarding_transcript")

    result = {
        "account_id": account_id,
        "pipeline_a": "skipped",
        "pipeline_b": "skipped",
        "error": None,
    }

    try:
        # ── Pipeline A: Demo ──────────────────────────────────────────────────
        v1_memo_path = OUTPUTS_DIR / account_id / "v1" / "account_memo.json"
        if not demo_path:
            log(f"[{account_id}] No demo transcript — skipping Pipeline A", "WARN")
        elif v1_memo_path.exists() and not force:
            log(f"[{account_id}] v1 already exists, skipping Pipeline A (use --force to rerun)")
            result["pipeline_a"] = "skipped_existing"
        else:
            log(f"[{account_id}] Pipeline A: extracting demo memo...")
            transcript = Path(demo_path).read_text(encoding="utf-8")
            memo_v1 = extract_demo(transcript, account_id)
            save_memo(memo_v1, account_id, "v1")
            spec_v1 = build_agent_spec(memo_v1, "v1")
            save_agent_spec(spec_v1, account_id, "v1")
            result["pipeline_a"] = "success"
            log(f"[{account_id}] Pipeline A complete ✅")

        # ── Pipeline B: Onboarding ────────────────────────────────────────────
        v2_memo_path = OUTPUTS_DIR / account_id / "v2" / "account_memo.json"
        if not ob_path:
            log(f"[{account_id}] No onboarding transcript — skipping Pipeline B", "WARN")
        elif v2_memo_path.exists() and not force:
            log(f"[{account_id}] v2 already exists, skipping Pipeline B (use --force to rerun)")
            result["pipeline_b"] = "skipped_existing"
        else:
            # Need v1 memo to run Pipeline B
            v1_memo_path = OUTPUTS_DIR / account_id / "v1" / "account_memo.json"
            if not v1_memo_path.exists():
                log(f"[{account_id}] v1 memo missing — cannot run Pipeline B", "ERROR")
                result["pipeline_b"] = "error_no_v1"
            else:
                log(f"[{account_id}] Pipeline B: extracting onboarding patch...")
                transcript = Path(ob_path).read_text(encoding="utf-8")
                existing_memo = json.loads(v1_memo_path.read_text())
                updated_memo, changes = extract_onboarding_patch(transcript, account_id, existing_memo)
                save_memo(updated_memo, account_id, "v2")
                spec_v2 = build_agent_spec(updated_memo, "v2")
                save_agent_spec(spec_v2, account_id, "v2")

                # Generate changelog
                memo_v1 = json.loads(v1_memo_path.read_text())
                diff_changes = deep_diff(memo_v1, updated_memo)
                account_dir = OUTPUTS_DIR / account_id
                changelog_json = {
                    "account_id": account_id,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "from_version": "v1",
                    "to_version": "v2",
                    "total_changes": len(diff_changes),
                    "changes": diff_changes,
                }
                (account_dir / "changelog.json").write_text(json.dumps(changelog_json, indent=2))
                md = render_markdown(account_id, diff_changes, memo_v1, updated_memo)
                (account_dir / "changelog.md").write_text(md)

                result["pipeline_b"] = "success"
                result["changes_count"] = len(diff_changes)
                log(f"[{account_id}] Pipeline B complete ✅ ({len(diff_changes)} changes)")

    except Exception as e:
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()
        log(f"[{account_id}] FAILED: {e}", "ERROR")

    return result


# ── Summary report ─────────────────────────────────────────────────────────────

def save_run_summary(results: list[dict]):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = LOGS_DIR / f"run_{ts}.json"

    summary = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "total_accounts": len(results),
        "pipeline_a_success": sum(1 for r in results if r.get("pipeline_a") == "success"),
        "pipeline_b_success": sum(1 for r in results if r.get("pipeline_b") == "success"),
        "errors": sum(1 for r in results if r.get("error")),
        "results": results,
    }
    path.write_text(json.dumps(summary, indent=2))
    log(f"Run summary saved: {path}")
    return summary


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Clara Answers – Batch Pipeline Runner")
    parser.add_argument("--dataset_dir", default="./dataset", help="Dataset directory")
    parser.add_argument("--account_id", help="Run single account only")
    parser.add_argument("--force", action="store_true", help="Overwrite existing outputs")
    parser.add_argument("--stage", choices=["a", "b", "all"], default="all",
                        help="Run only Pipeline A (demo), B (onboarding), or all")
    args = parser.parse_args()

    dataset_dir = Path(args.dataset_dir)
    if not dataset_dir.exists():
        print(f"ERROR: Dataset directory not found: {dataset_dir}")
        sys.exit(1)

    log("Clara Answers Pipeline Runner", "START")
    log(f"Dataset: {dataset_dir.resolve()}")
    log(f"Force rerun: {args.force}")

    accounts = discover_accounts(dataset_dir)

    if args.account_id:
        accounts = [a for a in accounts if a["account_id"] == args.account_id]
        if not accounts:
            log(f"Account {args.account_id} not found in dataset", "ERROR")
            sys.exit(1)

    log(f"Found {len(accounts)} accounts to process")

    # Filter stages
    if args.stage == "a":
        for a in accounts:
            a.pop("onboarding_transcript", None)
    elif args.stage == "b":
        for a in accounts:
            a.pop("demo_transcript", None)

    results = []
    for entry in accounts:
        log(f"--- Processing {entry['account_id']} ---")
        result = run_account(entry, force=args.force)
        results.append(result)

    summary = save_run_summary(results)

    print("\n" + "="*60)
    print(f"  PIPELINE COMPLETE")
    print(f"  Accounts processed : {summary['total_accounts']}")
    print(f"  Pipeline A success : {summary['pipeline_a_success']}")
    print(f"  Pipeline B success : {summary['pipeline_b_success']}")
    print(f"  Errors             : {summary['errors']}")
    print("="*60)

    if summary["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
