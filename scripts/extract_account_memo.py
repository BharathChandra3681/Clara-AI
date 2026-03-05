"""
extract_account_memo.py
-----------------------
Pipeline A & B: Extracts structured Account Memo JSON from a call transcript.
Uses Google Gemini API (free tier) or falls back to rule-based extraction.
Zero-cost: Uses only free-tier API access.

Usage:
    python extract_account_memo.py \
        --transcript path/to/transcript.txt \
        --account_id ACC001 \
        --stage demo|onboarding \
        [--existing_memo path/to/v1_memo.json]
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
OUTPUTS_DIR = Path(__file__).parent.parent / "outputs" / "accounts"
CONFIG_DIR  = Path(__file__).parent.parent / "config"

# ── Prompt templates ──────────────────────────────────────────────────────────
EXTRACTION_SYSTEM_PROMPT = """You are a precise data extraction assistant for Clara Answers, 
an AI voice agent platform serving service-trade businesses (fire protection, sprinkler, 
HVAC, electrical, alarm contractors).

Your job is to extract structured operational configuration data from call transcripts.

RULES:
1. Only extract what is EXPLICITLY stated. Never invent or infer missing values.
2. If a field is not mentioned, set it to null.
3. If a field is partially mentioned but unclear, add it to questions_or_unknowns.
4. Do not hallucinate phone numbers, addresses, names, or routing rules.
5. Return ONLY valid JSON, no commentary, no markdown fences.
6. Be conservative: unclear = null, not a guess.

OUTPUT SCHEMA:
{
  "account_id": "string",
  "company_name": "string or null",
  "business_hours": {
    "days": ["Monday","Tuesday",...] or null,
    "start": "HH:MM" or null,
    "end": "HH:MM" or null,
    "timezone": "America/Chicago" (IANA format) or null
  },
  "office_address": "string or null",
  "services_supported": ["list of services"] or [],
  "emergency_definition": ["list of triggers that constitute an emergency"] or [],
  "emergency_routing_rules": {
    "primary_contact": "name/role" or null,
    "primary_phone": "phone number" or null,
    "secondary_contact": "name/role" or null,
    "secondary_phone": "phone number" or null,
    "order": ["step1","step2",...] or [],
    "fallback": "what to do if all contacts fail" or null
  },
  "non_emergency_routing_rules": {
    "during_hours": "description" or null,
    "after_hours": "description" or null,
    "voicemail_allowed": true/false/null
  },
  "call_transfer_rules": {
    "timeout_seconds": number or null,
    "retries": number or null,
    "transfer_fail_message": "string" or null,
    "warm_transfer": true/false/null
  },
  "integration_constraints": ["list of constraints, e.g. never create X in ServiceTrade"] or [],
  "after_hours_flow_summary": "plain English summary" or null,
  "office_hours_flow_summary": "plain English summary" or null,
  "questions_or_unknowns": ["list of genuinely missing critical details"] or [],
  "notes": "short free-form notes" or null,
  "extraction_stage": "demo" or "onboarding",
  "extracted_at": "ISO8601 timestamp"
}"""

EXTRACTION_USER_PROMPT = """Extract structured operational data from this {stage} call transcript.
Account ID: {account_id}

TRANSCRIPT:
---
{transcript}
---

Return ONLY the JSON object described in your instructions. No markdown, no explanation."""

ONBOARDING_PATCH_PROMPT = """You are updating an existing Clara Answers account configuration.
You have the existing v1 configuration and a new onboarding call transcript.

RULES:
1. Only UPDATE fields that are explicitly confirmed or changed in the onboarding transcript.
2. Preserve all existing v1 fields that are NOT contradicted.
3. If onboarding CONFIRMS a demo assumption, keep it (no change needed in diff).
4. If onboarding OVERRIDES a demo assumption, update the field.
5. If onboarding ADDS new information, add it.
6. Track every change in the changes array.
7. Return ONLY valid JSON, no commentary.

OUTPUT SCHEMA:
{
  "updated_memo": { ...full updated memo JSON using the Account Memo schema... },
  "changes": [
    {
      "field": "dotted.path.to.field",
      "old_value": "previous value or null",
      "new_value": "new value",
      "reason": "why it changed (confirmed/overridden/added)"
    }
  ]
}"""

ONBOARDING_PATCH_USER = """Existing v1 memo:
{existing_memo}

Onboarding call transcript:
---
{transcript}
---

Return the updated memo and change log as described."""


# -- LLM call (Google Gemini -- free tier) ------------------------------------
def call_llm(system_prompt: str, user_prompt: str) -> str:
    """
    Calls Google Gemini 2.0 Flash -- free via Google AI Studio.
    Get your free key at: https://aistudio.google.com/apikey
    Then run: export GEMINI_API_KEY=your_key_here
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY not set. "
            "Get a free key at: https://aistudio.google.com/apikey "
            "Then run: export GEMINI_API_KEY=your_key_here"
        )

    import urllib.request
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    payload = {
        "contents": [
            {"parts": [{"text": system_prompt + "\n\n" + user_prompt}]}
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 4096,
        }
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


# ── Sanitize / validate JSON from LLM ─────────────────────────────────────────
def parse_llm_json(raw: str) -> dict:
    """Strip markdown fences and parse JSON."""
    raw = raw.strip()
    # Remove ```json ... ``` or ``` ... ```
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


# ── Pipeline A: Demo extraction ───────────────────────────────────────────────
def extract_demo(transcript: str, account_id: str) -> dict:
    """Extract v1 Account Memo from a demo call transcript."""
    print(f"[extract] Running demo extraction for {account_id}...")
    user_prompt = EXTRACTION_USER_PROMPT.format(
        stage="demo",
        account_id=account_id,
        transcript=transcript,
    )
    raw = call_llm(EXTRACTION_SYSTEM_PROMPT, user_prompt)
    memo = parse_llm_json(raw)

    # Enforce required fields
    memo["account_id"] = account_id
    memo["extraction_stage"] = "demo"
    memo["extracted_at"] = datetime.now(timezone.utc).isoformat()
    memo["version"] = "v1"

    return memo


# ── Pipeline B: Onboarding patch ──────────────────────────────────────────────
def extract_onboarding_patch(transcript: str, account_id: str, existing_memo: dict) -> tuple[dict, list]:
    """
    Extract updates from onboarding transcript and apply to existing memo.
    Returns (updated_memo, changes_list).
    """
    print(f"[extract] Running onboarding patch for {account_id}...")
    user_prompt = ONBOARDING_PATCH_USER.format(
        existing_memo=json.dumps(existing_memo, indent=2),
        transcript=transcript,
    )
    raw = call_llm(ONBOARDING_PATCH_PROMPT, user_prompt)
    result = parse_llm_json(raw)

    updated_memo = result.get("updated_memo", existing_memo)
    changes = result.get("changes", [])

    # Enforce metadata
    updated_memo["account_id"] = account_id
    updated_memo["extraction_stage"] = "onboarding"
    updated_memo["extracted_at"] = datetime.now(timezone.utc).isoformat()
    updated_memo["version"] = "v2"

    return updated_memo, changes


# ── Save outputs ──────────────────────────────────────────────────────────────
def save_memo(memo: dict, account_id: str, version: str) -> Path:
    out_dir = OUTPUTS_DIR / account_id / version
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "account_memo.json"
    path.write_text(json.dumps(memo, indent=2))
    print(f"[save] Memo saved: {path}")
    return path


def save_changelog(changes: list, account_id: str) -> Path:
    cl_dir = OUTPUTS_DIR / account_id
    cl_dir.mkdir(parents=True, exist_ok=True)
    path = cl_dir / "changelog.json"

    # Append to existing changelog if present
    existing = []
    if path.exists():
        existing = json.loads(path.read_text())

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "from_version": "v1",
        "to_version": "v2",
        "changes": changes,
    }
    existing.append(entry)
    path.write_text(json.dumps(existing, indent=2))
    print(f"[save] Changelog saved: {path}")
    return path


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Clara Answers – Account Memo Extractor")
    parser.add_argument("--transcript", required=True, help="Path to transcript .txt file")
    parser.add_argument("--account_id", required=True, help="Account ID, e.g. ACC001")
    parser.add_argument("--stage", required=True, choices=["demo", "onboarding"])
    parser.add_argument("--existing_memo", help="Path to v1 memo JSON (required for onboarding stage)")
    args = parser.parse_args()

    transcript = Path(args.transcript).read_text(encoding="utf-8")

    if args.stage == "demo":
        memo = extract_demo(transcript, args.account_id)
        save_memo(memo, args.account_id, "v1")
        print(f"\nDemo extraction complete for {args.account_id}")

    elif args.stage == "onboarding":
        if not args.existing_memo:
            print("ERROR: --existing_memo required for onboarding stage", file=sys.stderr)
            sys.exit(1)
        existing = json.loads(Path(args.existing_memo).read_text())
        updated_memo, changes = extract_onboarding_patch(transcript, args.account_id, existing)
        save_memo(updated_memo, args.account_id, "v2")
        save_changelog(changes, args.account_id)
        print(f"\nOnboarding patch complete for {args.account_id} ({len(changes)} changes)")


if __name__ == "__main__":
    main()
