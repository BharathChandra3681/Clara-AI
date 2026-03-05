"""
ingest.py
---------
Drop any audio/video file in and this script:
  1. Transcribes it with Whisper (free, local)
  2. Assigns an account_id
  3. Runs Pipeline A (demo) or B (onboarding) automatically
  4. Syncs the agent to Retell

Usage:
    # Single file
    python scripts/ingest.py --file downloads/audio.m4a --account_id BEN001 --stage demo

    # Auto-detect stage from filename
    python scripts/ingest.py --file downloads/audio.m4a --account_id BEN001

    # Watch a folder — processes any new audio dropped in automatically
    python scripts/ingest.py --watch downloads/

Install Whisper first (one-time):
    pip install openai-whisper
"""

import argparse
import json
import os
import sys
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

DATASET_DIR = Path(__file__).parent.parent / "dataset"
OUTPUTS_DIR = Path(__file__).parent.parent / "outputs" / "accounts"
PROCESSED_LOG = Path(__file__).parent.parent / "outputs" / "logs" / "ingested.json"

sys.path.insert(0, str(Path(__file__).parent))


# ── Whisper transcription ──────────────────────────────────────────────────────

def transcribe(audio_path: Path, model_size: str = "base") -> str:
    """
    Transcribe audio/video file using OpenAI Whisper (runs locally, free).
    Model sizes: tiny, base, small, medium, large
    'base' is a good balance of speed and accuracy.
    """
    try:
        import whisper
    except ImportError:
        print("❌ Whisper not installed. Run: pip install openai-whisper")
        sys.exit(1)

    print(f"[whisper] Loading model '{model_size}'...")
    model = whisper.load_model(model_size)

    print(f"[whisper] Transcribing {audio_path.name} ...")
    result = model.transcribe(str(audio_path))
    text = result["text"].strip()

    print(f"[whisper] ✅ Transcription complete ({len(text)} chars)")
    return text


# ── Stage detection ────────────────────────────────────────────────────────────

def detect_stage(filename: str, account_id: str) -> str:
    """
    Auto-detect if file is demo or onboarding based on filename or
    whether a v1 memo already exists for this account.
    """
    name_lower = filename.lower()
    if any(w in name_lower for w in ["onboard", "ob_", "onboarding"]):
        return "onboarding"
    if any(w in name_lower for w in ["demo", "discovery", "intro"]):
        return "demo"

    # If v1 already exists → this must be onboarding
    v1_path = OUTPUTS_DIR / account_id / "v1" / "account_memo.json"
    if v1_path.exists():
        print(f"[detect] v1 exists for {account_id} → treating as onboarding")
        return "onboarding"

    return "demo"


# ── Main ingest ────────────────────────────────────────────────────────────────

def ingest_file(file_path: Path, account_id: str, stage: str = None,
                whisper_model: str = "base", sync_retell: bool = False):

    print(f"\n{'='*55}")
    print(f"  Ingesting: {file_path.name}")
    print(f"  Account:   {account_id}")

    # Auto-detect stage if not provided
    if not stage:
        stage = detect_stage(file_path.name, account_id)
    print(f"  Stage:     {stage}")
    print(f"{'='*55}")

    # Step 1: Transcribe
    suffix = file_path.suffix.lower()
    text_extensions = [".txt", ".md"]

    if suffix in text_extensions:
        print(f"[ingest] Text file detected — skipping transcription")
        transcript = file_path.read_text(encoding="utf-8")
    else:
        transcript = transcribe(file_path, whisper_model)

    # Step 2: Save transcript
    account_dir = DATASET_DIR / account_id
    account_dir.mkdir(parents=True, exist_ok=True)
    transcript_filename = f"{'demo' if stage == 'demo' else 'onboarding'}_transcript.txt"
    transcript_path = account_dir / transcript_filename
    transcript_path.write_text(transcript, encoding="utf-8")
    print(f"[ingest] Transcript saved: {transcript_path}")

    # Step 3: Update manifest
    update_manifest(account_id, stage, transcript_path)

    # Step 4: Run pipeline
    from run_demo import (
        extract_memo_rule_based, patch_memo,
        OUTPUTS_DIR as OUT_DIR
    )
    from generate_agent_spec import build_agent_spec, save_agent_spec
    from generate_changelog import deep_diff, render_markdown

    if stage == "demo":
        print(f"[ingest] Running Pipeline A...")
        memo = extract_memo_rule_based(transcript, account_id, "demo")

        # Try Gemini if available
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if gemini_key:
            try:
                from extract_account_memo import extract_demo
                print(f"[ingest] Gemini key found — using LLM extraction...")
                memo = extract_demo(transcript, account_id)
            except Exception as e:
                print(f"[ingest] ⚠️  Gemini failed ({e}), falling back to rule-based")

        out_dir = OUT_DIR / account_id / "v1"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "account_memo.json").write_text(json.dumps(memo, indent=2))
        spec = build_agent_spec(memo, "v1")
        save_agent_spec(spec, account_id, "v1")
        print(f"[ingest] ✅ Pipeline A complete for {account_id}")

    elif stage == "onboarding":
        v1_path = OUT_DIR / account_id / "v1" / "account_memo.json"
        if not v1_path.exists():
            print(f"[ingest] ❌ No v1 memo found for {account_id}. Run demo first.")
            return

        print(f"[ingest] Running Pipeline B...")
        existing = json.loads(v1_path.read_text())

        # Try Gemini if available
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if gemini_key:
            try:
                from extract_account_memo import extract_onboarding_patch
                print(f"[ingest] Gemini key found — using LLM extraction...")
                updated_memo, changes = extract_onboarding_patch(transcript, account_id, existing)
            except Exception as e:
                print(f"[ingest] ⚠️  Gemini failed ({e}), falling back to rule-based")
                updated_memo, changes = patch_memo(existing, transcript, account_id)
        else:
            updated_memo, changes = patch_memo(existing, transcript, account_id)

        out_dir = OUT_DIR / account_id / "v2"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "account_memo.json").write_text(json.dumps(updated_memo, indent=2))
        spec_v2 = build_agent_spec(updated_memo, "v2")
        save_agent_spec(spec_v2, account_id, "v2")

        # Changelog
        diff = deep_diff(existing, updated_memo)
        acc_dir = OUT_DIR / account_id
        (acc_dir / "changelog.json").write_text(json.dumps({
            "account_id": account_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "from_version": "v1", "to_version": "v2",
            "total_changes": len(diff), "changes": diff
        }, indent=2))
        (acc_dir / "changelog.md").write_text(
            render_markdown(account_id, diff, existing, updated_memo)
        )
        print(f"[ingest] ✅ Pipeline B complete for {account_id} ({len(diff)} changes)")

    # Step 5: Optional Retell sync
    if sync_retell:
        retell_key = os.environ.get("RETELL_API_KEY")
        if retell_key:
            print(f"[ingest] Syncing to Retell...")
            from retell_sync import sync_account
            version = "v1" if stage == "demo" else "v2"
            sync_account(account_id, version)
        else:
            print(f"[ingest] ⚠️  RETELL_API_KEY not set — skipping Retell sync")

    # Step 6: Log ingestion
    log_ingestion(file_path, account_id, stage)

    # Rebuild dashboard
    try:
        from build_dashboard import build_dashboard
        build_dashboard()
        print(f"[ingest] Dashboard updated")
    except Exception:
        pass

    print(f"\n✅ Done: {account_id} ({stage})")


# ── Manifest updater ───────────────────────────────────────────────────────────

def update_manifest(account_id: str, stage: str, transcript_path: Path):
    manifest_path = DATASET_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []

    existing = next((e for e in manifest if e["account_id"] == account_id), None)
    rel_path = str(transcript_path.relative_to(DATASET_DIR))

    if existing:
        if stage == "demo":
            existing["demo_transcript"] = rel_path
        else:
            existing["onboarding_transcript"] = rel_path
    else:
        entry = {"account_id": account_id}
        if stage == "demo":
            entry["demo_transcript"] = rel_path
        else:
            entry["onboarding_transcript"] = rel_path
        manifest.append(entry)

    manifest_path.write_text(json.dumps(manifest, indent=2))


# ── Ingestion log ──────────────────────────────────────────────────────────────

def log_ingestion(file_path: Path, account_id: str, stage: str):
    PROCESSED_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = json.loads(PROCESSED_LOG.read_text()) if PROCESSED_LOG.exists() else []
    log.append({
        "file": file_path.name,
        "account_id": account_id,
        "stage": stage,
        "ingested_at": datetime.now(timezone.utc).isoformat()
    })
    PROCESSED_LOG.write_text(json.dumps(log, indent=2))


# ── Folder watcher ─────────────────────────────────────────────────────────────

def watch_folder(watch_dir: Path, whisper_model: str, sync_retell: bool):
    """
    Watch a folder for new audio/video files.
    Expected filename format: ACCOUNT_ID_stage.m4a
    Examples:
        BEN001_demo.m4a
        BEN001_onboarding.m4a
        ACC002_demo.mp4
    """
    AUDIO_EXTS = {".m4a", ".mp3", ".mp4", ".wav", ".ogg", ".flac", ".webm"}
    processed = set()

    print(f"👀 Watching folder: {watch_dir}")
    print(f"   Drop audio files named: ACCOUNT_ID_demo.m4a or ACCOUNT_ID_onboarding.m4a")
    print(f"   Press Ctrl+C to stop\n")

    while True:
        for f in watch_dir.iterdir():
            if f.suffix.lower() not in AUDIO_EXTS:
                continue
            if f.name in processed:
                continue

            processed.add(f.name)
            print(f"\n[watch] New file detected: {f.name}")

            # Parse account_id and stage from filename
            # Format: BEN001_demo.m4a or BEN001_onboarding.m4a
            stem = f.stem  # e.g. "BEN001_demo"
            parts = stem.split("_")

            if len(parts) >= 2:
                account_id = parts[0].upper()
                stage_hint = parts[1].lower()
                stage = "onboarding" if "onboard" in stage_hint else "demo"
            else:
                account_id = stem.upper()
                stage = None  # auto-detect

            try:
                ingest_file(f, account_id, stage, whisper_model, sync_retell)
            except Exception as e:
                print(f"[watch] ❌ Failed to process {f.name}: {e}")

        time.sleep(3)  # check every 3 seconds


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Clara Answers – Auto Ingest")
    parser.add_argument("--file", help="Path to audio/video/transcript file")
    parser.add_argument("--account_id", help="Account ID e.g. BEN001")
    parser.add_argument("--stage", choices=["demo", "onboarding"], help="Auto-detected if not set")
    parser.add_argument("--watch", help="Folder to watch for new files")
    parser.add_argument("--model", default="base",
                        choices=["tiny", "base", "small", "medium"],
                        help="Whisper model size (default: base)")
    parser.add_argument("--sync-retell", action="store_true",
                        help="Auto-sync to Retell after processing")
    args = parser.parse_args()

    if args.watch:
        watch_folder(Path(args.watch), args.model, args.sync_retell)
    elif args.file:
        if not args.account_id:
            # Try to parse from filename
            stem = Path(args.file).stem.split("_")[0].upper()
            args.account_id = stem
            print(f"[ingest] No account_id given — using '{stem}' from filename")
        ingest_file(
            Path(args.file),
            args.account_id,
            args.stage,
            args.model,
            args.sync_retell
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()