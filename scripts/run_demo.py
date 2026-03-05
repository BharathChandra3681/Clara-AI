"""
run_demo.py
-----------
Zero-cost demonstration runner.
Processes all 5 accounts using rule-based extraction (no LLM API key needed).
Generates all required outputs: account memos, agent specs, changelogs.

Usage:
    python run_demo.py
    python run_demo.py --account_id ACC001
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

DATASET_DIR = Path(__file__).parent.parent / "dataset"
OUTPUTS_DIR = Path(__file__).parent.parent / "outputs" / "accounts"
LOGS_DIR    = Path(__file__).parent.parent / "outputs" / "logs"

sys.path.insert(0, str(Path(__file__).parent))
from generate_agent_spec import build_agent_spec, save_agent_spec
from generate_changelog import deep_diff, render_markdown


# ── Rule-based field extractors ────────────────────────────────────────────────

def extract_company_name(text: str) -> str | None:
    patterns = [
        r"(?:we're|we are|I'm with|I'm from|this is)\s+([A-Z][A-Za-z\s&\-']+?)(?:\s*[.,\n]|\s+and\b|\s+based\b|\s+out\b)",
        r"([A-Z][A-Za-z\s&\-]+(?:Fire|HVAC|Electrical|Alarm|Mechanical|Plumbing|Protection|Services?|Contractors?|Systems?|Solutions?))",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            name = m.group(1).strip().rstrip(".,")
            if 3 < len(name) < 60:
                return name
    return None


def extract_business_hours(text: str) -> dict:
    bh = {"days": None, "start": None, "end": None, "timezone": None}

    # Days
    day_patterns = [
        (r"Monday\s+through\s+Friday", ["Monday","Tuesday","Wednesday","Thursday","Friday"]),
        (r"Monday\s*[-–]\s*Friday",    ["Monday","Tuesday","Wednesday","Thursday","Friday"]),
        (r"Mon(?:day)?\s*-\s*Fri(?:day)?", ["Monday","Tuesday","Wednesday","Thursday","Friday"]),
        (r"seven\s+days\s+a\s+week",   ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]),
        (r"Monday\s+through\s+Saturday", ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]),
    ]
    for pat, days in day_patterns:
        if re.search(pat, text, re.IGNORECASE):
            bh["days"] = days
            break

    # Sunday override
    sun_m = re.search(r"Sunday\s+(?:is\s+)?(?:now\s+)?(\d{1,2}(?::\d{2})?)\s*(?:AM|PM|am|pm)?\s+to\s+(\d{1,2}(?::\d{2})?)\s*(?:AM|PM|am|pm)?", text, re.IGNORECASE)
    if sun_m and bh["days"] and "Sunday" not in bh["days"]:
        bh["days"].append("Sunday")

    # Time - look for patterns like "seven to five" or "8 to 5" or "7:00 AM to 4:00 PM"
    time_pattern = re.search(
        r"(\d{1,2}(?::\d{2})?)\s*(AM|PM|am|pm)?\s+to\s+(\d{1,2}(?::\d{2})?)\s*(AM|PM|am|pm)?",
        text
    )
    word_times = {
        "seven": "7:00", "eight": "8:00", "nine": "9:00", "ten": "10:00",
        "eleven": "11:00", "twelve": "12:00", "one": "1:00", "two": "2:00",
        "three": "3:00", "four": "4:00", "five": "5:00", "six": "6:00",
    }
    word_pattern = re.search(
        r"(seven|eight|nine|ten|eleven|twelve|one|two|three|four|five|six)\s+(?:AM\s+)?to\s+(seven|eight|nine|ten|eleven|twelve|one|two|three|four|five|six)",
        text, re.IGNORECASE
    )

    if time_pattern:
        start_h = time_pattern.group(1)
        start_ampm = time_pattern.group(2) or ""
        end_h = time_pattern.group(3)
        end_ampm = time_pattern.group(4) or ""
        bh["start"] = f"{start_h} {start_ampm}".strip()
        bh["end"] = f"{end_h} {end_ampm}".strip()
    elif word_pattern:
        bh["start"] = word_times.get(word_pattern.group(1).lower())
        bh["end"] = word_times.get(word_pattern.group(2).lower())

    # Timezone
    tz_map = {
        "Central": "America/Chicago",
        "Eastern": "America/New_York",
        "Mountain": "America/Denver",
        "Pacific": "America/Los_Angeles",
        "MST": "America/Denver",
        "CST": "America/Chicago",
        "EST": "America/New_York",
        "PST": "America/Los_Angeles",
    }
    for abbr, iana in tz_map.items():
        if re.search(r'\b' + abbr + r'\b', text):
            bh["timezone"] = iana
            break

    return bh


def extract_address(text: str) -> str | None:
    addr = re.search(
        r'\d{3,5}\s+[A-Z][a-zA-Z\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Court|Ct|Place|Pl)[^\n,]*,\s*[A-Z][a-zA-Z\s]+,\s*[A-Z]{2,}\s*\d{5}',
        text
    )
    if addr:
        return addr.group(0).strip()
    # Partial
    partial = re.search(r'\d{3,5}\s+[A-Z][a-zA-Z\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr)[^\n,]*', text)
    if partial:
        return partial.group(0).strip()
    return None


def extract_phone(text: str, context_before: str = "") -> str | None:
    phones = re.findall(r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}', text)
    if phones:
        return phones[0]
    return None


def extract_phones_by_role(text: str) -> dict:
    """Extract phone numbers with their associated context."""
    result = {}
    lines = text.split('\n')
    for line in lines:
        phones = re.findall(r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}', line)
        if not phones:
            continue
        line_lower = line.lower()
        phone = phones[0]
        if any(w in line_lower for w in ["primary", "on-call cell", "on call", "dispatch"]):
            result["primary_phone"] = phone
        elif any(w in line_lower for w in ["backup", "secondary", "second"]):
            result["secondary_phone"] = phone
        elif any(w in line_lower for w in ["main office", "office line"]):
            result["office_phone"] = phone
        elif any(w in line_lower for w in ["my direct", "my cell", "my number"]) and "primary_phone" in result:
            result.setdefault("secondary_phone", phone)
    return result


def extract_emergency_definitions(text: str) -> list:
    triggers = []
    # Look for "emergency" context
    emerg_section = re.search(
        r'(?:emergency|emergencies)[^\n]*\n((?:[-•*].*\n?){1,10})',
        text, re.IGNORECASE
    )
    if emerg_section:
        items = re.findall(r'[-•*]\s*(.+)', emerg_section.group(1))
        triggers.extend([i.strip() for i in items])

    # Pattern: listed after "what would you consider an emergency" or similar
    list_pattern = re.search(
        r'(?:emergency|emergencies)[^.]*[.:\n]\s*((?:[A-Z][^.]+[.]\s*){1,8})',
        text, re.IGNORECASE
    )

    # Also look for explicit comma-separated lists describing emergencies
    inline = re.findall(
        r'(?:active\s+\w+|system\s+failure|power\s+outage|gas\s+leak|water\s+(?:main\s+)?break|fire\s+alarm|sprinkler\s+discharge|boiler\s+failure|CO\s+alarm|carbon\s+monoxide|sewage\s+backup|pipe\s+burst|kitchen\s+suppression|smoke\s+without)',
        text, re.IGNORECASE
    )
    for item in inline:
        normalized = item.strip()
        if normalized.lower() not in [t.lower() for t in triggers]:
            triggers.append(normalized)

    return list(dict.fromkeys(triggers))  # deduplicate preserving order


def extract_services(text: str) -> list:
    service_keywords = [
        "fire suppression", "sprinkler systems", "alarm systems", "fire protection",
        "HVAC", "electrical", "plumbing", "gas lines", "boiler systems",
        "installation", "maintenance", "repairs", "inspection", "monitoring",
        "mechanical", "fire alarm", "suppression", "refrigeration"
    ]
    found = []
    for kw in service_keywords:
        if re.search(r'\b' + re.escape(kw) + r'\b', text, re.IGNORECASE):
            found.append(kw.lower())
    return list(dict.fromkeys(found))


def extract_integration_constraints(text: str) -> list:
    constraints = []
    patterns = [
        r"never\s+create\s+[^\n.]+",
        r"do\s+not\s+create\s+[^\n.]+",
        r"don't\s+create\s+[^\n.]+",
        r"never\s+auto-create\s+[^\n.]+",
        r"no\s+job\s+creation\s+[^\n.]+",
    ]
    for p in patterns:
        matches = re.findall(p, text, re.IGNORECASE)
        for m in matches:
            clean = m.strip().rstrip(".,")
            if len(clean) > 10:
                constraints.append(clean)
    return list(dict.fromkeys(constraints))


def extract_questions_or_unknowns(text: str, memo: dict) -> list:
    unknowns = []
    critical_fields = [
        ("emergency_routing_rules.primary_phone", memo.get("emergency_routing_rules", {}).get("primary_phone")),
        ("business_hours.timezone", memo.get("business_hours", {}).get("timezone")),
        ("business_hours.start", memo.get("business_hours", {}).get("start")),
        ("call_transfer_rules.timeout_seconds", memo.get("call_transfer_rules", {}).get("timeout_seconds")),
    ]
    for field_name, value in critical_fields:
        if not value:
            unknowns.append(f"Missing: {field_name} — not provided in this call")

    # Check for explicit unknowns mentioned in transcript
    unknown_patterns = [
        r"I don't have (?:that|their|his|her) number",
        r"I don't know the details",
        r"haven't thought that through",
        r"need to check with",
        r"not sure about",
        r"don't know (?:yet|right now)",
    ]
    for p in unknown_patterns:
        matches = re.findall(r'.{0,60}' + p + r'.{0,60}', text, re.IGNORECASE)
        for m in matches:
            unknowns.append(f"Caller indicated uncertainty: '{m.strip()}'")

    return unknowns


# ── Full rule-based extraction ─────────────────────────────────────────────────

def extract_memo_rule_based(transcript: str, account_id: str, stage: str) -> dict:
    """Extract account memo using rules only — zero API cost."""

    bh = extract_business_hours(transcript)
    phones = extract_phones_by_role(transcript)

    # Extract contacts with names
    primary_contact = None
    secondary_contact = None
    name_phone = re.findall(
        r'([A-Z][a-z]+ [A-Z][a-z]+)[^\n]*?(\d{3}[-.\s]?\d{3}[-.\s]?\d{4})',
        transcript
    )
    if name_phone:
        primary_contact = name_phone[0][0] if len(name_phone) > 0 else None
        secondary_contact = name_phone[1][0] if len(name_phone) > 1 else None

    # Extract timeout
    timeout = None
    timeout_m = re.search(r'(\d{1,3})\s*seconds?', transcript, re.IGNORECASE)
    if timeout_m:
        timeout = int(timeout_m.group(1))

    # Build emergency routing from phones
    all_phones = re.findall(r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}', transcript)
    primary_phone = all_phones[0] if all_phones else None
    secondary_phone = all_phones[1] if len(all_phones) > 1 else None

    memo = {
        "account_id": account_id,
        "company_name": extract_company_name(transcript),
        "business_hours": bh,
        "office_address": extract_address(transcript),
        "services_supported": extract_services(transcript),
        "emergency_definition": extract_emergency_definitions(transcript),
        "emergency_routing_rules": {
            "primary_contact": primary_contact,
            "primary_phone": primary_phone,
            "secondary_contact": secondary_contact,
            "secondary_phone": secondary_phone,
            "order": ["primary_contact", "secondary_contact"] if primary_contact else [],
            "fallback": None,
        },
        "non_emergency_routing_rules": {
            "during_hours": "transfer to main office line" if "main office" in transcript.lower() else "route to available staff",
            "after_hours": "collect name, number, issue description and confirm callback next business day",
            "voicemail_allowed": "voicemail" in transcript.lower(),
        },
        "call_transfer_rules": {
            "timeout_seconds": timeout,
            "retries": 1,
            "transfer_fail_message": None,
            "warm_transfer": None,
        },
        "integration_constraints": extract_integration_constraints(transcript),
        "after_hours_flow_summary": (
            "Greet caller, identify if emergency. "
            "If emergency: collect name, phone, address immediately, attempt transfer, assure follow-up if fails. "
            "If non-emergency: collect contact info and confirm callback next business day."
        ),
        "office_hours_flow_summary": (
            "Greet caller, understand request, collect name and number, "
            "route or transfer as appropriate, confirm next steps, close."
        ),
        "notes": None,
        "extraction_stage": stage,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "version": "v1" if stage == "demo" else "v2",
    }

    memo["questions_or_unknowns"] = extract_questions_or_unknowns(transcript, memo)
    return memo


# ── Onboarding patch (rule-based) ──────────────────────────────────────────────

def patch_memo(v1_memo: dict, onboarding_transcript: str, account_id: str) -> tuple[dict, list]:
    """Apply onboarding transcript on top of v1 memo."""
    import copy
    v2 = copy.deepcopy(v1_memo)
    changes = []

    # Extract fresh memo from onboarding transcript
    ob_memo = extract_memo_rule_based(onboarding_transcript, account_id, "onboarding")

    # Selective update: only override fields that are now populated
    fields_to_update = [
        "company_name", "office_address", "services_supported",
        "emergency_definition", "integration_constraints", "notes"
    ]

    for field in fields_to_update:
        new_val = ob_memo.get(field)
        old_val = v2.get(field)
        if new_val and new_val != old_val:
            # For lists, merge and deduplicate
            if isinstance(new_val, list) and isinstance(old_val, list):
                merged = list(dict.fromkeys(old_val + new_val))
                if merged != old_val:
                    changes.append({"field": field, "old_value": old_val, "new_value": merged, "change_type": "modified"})
                    v2[field] = merged
            else:
                changes.append({"field": field, "old_value": old_val, "new_value": new_val, "change_type": "modified"})
                v2[field] = new_val

    # Update nested fields
    # Business hours
    ob_bh = ob_memo.get("business_hours", {})
    v2_bh = v2.setdefault("business_hours", {})
    for sub in ["days", "start", "end", "timezone"]:
        if ob_bh.get(sub) and ob_bh[sub] != v2_bh.get(sub):
            changes.append({
                "field": f"business_hours.{sub}",
                "old_value": v2_bh.get(sub),
                "new_value": ob_bh[sub],
                "change_type": "modified" if v2_bh.get(sub) else "added"
            })
            v2_bh[sub] = ob_bh[sub]

    # Emergency routing
    ob_er = ob_memo.get("emergency_routing_rules", {})
    v2_er = v2.setdefault("emergency_routing_rules", {})
    for sub in ["primary_phone", "secondary_phone", "primary_contact", "secondary_contact", "fallback"]:
        if ob_er.get(sub) and ob_er[sub] != v2_er.get(sub):
            changes.append({
                "field": f"emergency_routing_rules.{sub}",
                "old_value": v2_er.get(sub),
                "new_value": ob_er[sub],
                "change_type": "modified" if v2_er.get(sub) else "added"
            })
            v2_er[sub] = ob_er[sub]

    # Call transfer rules
    ob_ctr = ob_memo.get("call_transfer_rules", {})
    v2_ctr = v2.setdefault("call_transfer_rules", {})
    if ob_ctr.get("timeout_seconds") and ob_ctr["timeout_seconds"] != v2_ctr.get("timeout_seconds"):
        changes.append({
            "field": "call_transfer_rules.timeout_seconds",
            "old_value": v2_ctr.get("timeout_seconds"),
            "new_value": ob_ctr["timeout_seconds"],
            "change_type": "modified" if v2_ctr.get("timeout_seconds") else "added"
        })
        v2_ctr["timeout_seconds"] = ob_ctr["timeout_seconds"]

    # Update metadata
    v2["version"] = "v2"
    v2["extraction_stage"] = "onboarding"
    v2["extracted_at"] = datetime.now(timezone.utc).isoformat()
    v2["questions_or_unknowns"] = [
        q for q in v2.get("questions_or_unknowns", [])
        if "primary_phone" not in q or v2_er.get("primary_phone")
    ]

    return v2, changes


# ── Account runner ─────────────────────────────────────────────────────────────

def run_account(account_id: str, demo_path: str, ob_path: str | None) -> dict:
    result = {"account_id": account_id, "pipeline_a": "skipped", "pipeline_b": "skipped", "error": None}

    try:
        # Pipeline A
        print(f"\n[{account_id}] Pipeline A: Demo extraction...")
        transcript = Path(demo_path).read_text(encoding="utf-8")
        v1_memo = extract_memo_rule_based(transcript, account_id, "demo")

        out_dir = OUTPUTS_DIR / account_id / "v1"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "account_memo.json").write_text(json.dumps(v1_memo, indent=2))

        spec_v1 = build_agent_spec(v1_memo, "v1")
        save_agent_spec(spec_v1, account_id, "v1")
        result["pipeline_a"] = "success"
        print(f"[{account_id}]  Pipeline A complete")

        # Pipeline B
        if ob_path:
            print(f"[{account_id}] Pipeline B: Onboarding patch...")
            ob_transcript = Path(ob_path).read_text(encoding="utf-8")
            v2_memo, changes = patch_memo(v1_memo, ob_transcript, account_id)

            out_dir_v2 = OUTPUTS_DIR / account_id / "v2"
            out_dir_v2.mkdir(parents=True, exist_ok=True)
            (out_dir_v2 / "account_memo.json").write_text(json.dumps(v2_memo, indent=2))

            spec_v2 = build_agent_spec(v2_memo, "v2")
            save_agent_spec(spec_v2, account_id, "v2")

            # Changelog
            diff_changes = deep_diff(v1_memo, v2_memo)
            account_dir = OUTPUTS_DIR / account_id
            changelog_json = {
                "account_id": account_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "from_version": "v1", "to_version": "v2",
                "total_changes": len(diff_changes),
                "changes": diff_changes,
            }
            (account_dir / "changelog.json").write_text(json.dumps(changelog_json, indent=2))
            md = render_markdown(account_id, diff_changes, v1_memo, v2_memo)
            (account_dir / "changelog.md").write_text(md)

            result["pipeline_b"] = "success"
            result["changes_count"] = len(diff_changes)
            print(f"[{account_id}]  Pipeline B complete ({len(diff_changes)} changes detected)")
        else:
            print(f"[{account_id}]   No onboarding transcript — skipping Pipeline B")

    except Exception as e:
        import traceback
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()
        print(f"[{account_id}]  Error: {e}")

    return result


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account_id", help="Run single account only")
    args = parser.parse_args()

    manifest = json.loads((DATASET_DIR / "manifest.json").read_text())

    if args.account_id:
        manifest = [e for e in manifest if e["account_id"] == args.account_id]

    print(f" Clara AI Pipeline — Processing {len(manifest)} accounts")
    print(f"   Dataset:  {DATASET_DIR}")
    print(f"   Outputs:  {OUTPUTS_DIR}")

    results = []
    for entry in manifest:
        aid = entry["account_id"]
        demo  = str(DATASET_DIR / entry["demo_transcript"])
        ob    = str(DATASET_DIR / entry["onboarding_transcript"]) if entry.get("onboarding_transcript") else None
        results.append(run_account(aid, demo, ob))

    # Summary
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    summary = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "total_accounts": len(results),
        "pipeline_a_success": sum(1 for r in results if r["pipeline_a"] == "success"),
        "pipeline_b_success": sum(1 for r in results if r["pipeline_b"] == "success"),
        "errors": sum(1 for r in results if r["error"]),
        "results": results,
    }
    (LOGS_DIR / f"run_{ts}.json").write_text(json.dumps(summary, indent=2))

    print(f"\n{'='*55}")
    print(f"  PIPELINE COMPLETE")
    print(f"  Accounts     : {summary['total_accounts']}")
    print(f"  Pipeline A  : {summary['pipeline_a_success']}")
    print(f"  Pipeline B  : {summary['pipeline_b_success']}")
    print(f"  Errors    : {summary['errors']}")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
