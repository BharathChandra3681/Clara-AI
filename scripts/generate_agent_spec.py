"""
generate_agent_spec.py
----------------------
Generates a Retell Agent Draft Spec (JSON) from an Account Memo JSON.
This is the "prompt generator" step in the pipeline.

Usage:
    python generate_agent_spec.py \
        --memo path/to/account_memo.json \
        --account_id ACC001 \
        --version v1|v2
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

OUTPUTS_DIR = Path(__file__).parent.parent / "outputs" / "accounts"

# ── Prompt builder ─────────────────────────────────────────────────────────────

def build_system_prompt(memo: dict) -> str:
    """
    Build the full Clara agent system prompt from the structured memo.
    Follows required conversation hygiene from the assignment spec.
    """
    company = memo.get("company_name") or "our company"
    bh = memo.get("business_hours") or {}
    days = ", ".join(bh.get("days") or []) or "Monday through Friday"
    start = bh.get("start") or "8:00 AM"
    end = bh.get("end") or "5:00 PM"
    tz = bh.get("timezone") or "local time"
    address = memo.get("office_address") or "our office"
    services = ", ".join(memo.get("services_supported") or ["service requests"])

    emerg_defs = memo.get("emergency_definition") or []
    emerg_text = (
        "\n".join(f"  - {e}" for e in emerg_defs)
        if emerg_defs
        else "  - Active fire, sprinkler discharge, or alarm system failure"
    )

    er = memo.get("emergency_routing_rules") or {}
    primary = er.get("primary_contact") or "the on-call technician"
    primary_phone = er.get("primary_phone") or "[PRIMARY_PHONE]"
    secondary = er.get("secondary_contact") or "the backup on-call"
    secondary_phone = er.get("secondary_phone") or "[SECONDARY_PHONE]"
    fallback = er.get("fallback") or "assure the caller dispatch has been notified and someone will call them back within 15 minutes"

    ner = memo.get("non_emergency_routing_rules") or {}
    ner_during = ner.get("during_hours") or "transfer to the main office line"
    ner_after = ner.get("after_hours") or "take a message and confirm a callback during business hours"

    ctr = memo.get("call_transfer_rules") or {}
    timeout = ctr.get("timeout_seconds") or 30
    transfer_fail_msg = ctr.get("transfer_fail_message") or (
        "I'm sorry, I wasn't able to reach anyone right now. "
        "I've recorded your information and someone will call you back shortly."
    )

    integrations = memo.get("integration_constraints") or []
    integration_note = (
        "\n".join(f"  - {c}" for c in integrations)
        if integrations
        else "  - Follow standard workflow unless instructed otherwise"
    )

    prompt = f"""# Clara – AI Voice Agent for {company}

## Identity
You are Clara, a professional and warm AI receptionist for {company}.
You handle inbound calls for service requests, emergencies, scheduling, and general inquiries.
You are calm, efficient, and empathetic. You never mention that you are an AI unless directly asked.
You never mention function calls, tools, or internal systems to callers.

## Business Hours
- Days: {days}
- Hours: {start} to {end} ({tz})
- Office Address: {address}

## Services Supported
{services}

## Emergency Definitions
The following situations are classified as emergencies requiring immediate dispatch:
{emerg_text}

## Integration Constraints (Internal — never mention to caller)
{integration_note}

---

## BUSINESS HOURS CALL FLOW

When a call comes in during business hours ({days}, {start}–{end} {tz}):

1. **Greeting**
   - "Thank you for calling {company}, this is Clara. How can I help you today?"

2. **Understand Purpose**
   - Listen to the caller's reason for calling.
   - Identify if it is an emergency, a service request, scheduling, or general inquiry.

3. **Collect Caller Information**
   - "May I get your name?"
   - "And the best phone number to reach you?"
   - For service calls: "What is the address of the property?"

4. **Route or Transfer**
   - For emergencies: Follow the Emergency Flow below immediately.
   - For service requests: "{ner_during}"
   - Attempt transfer. Allow up to {timeout} seconds.

5. **If Transfer Fails**
   - Say: "{transfer_fail_msg}"
   - Confirm: "I have your name as [name] and your number as [number]. Is that correct?"
   - Assure callback: "Someone from our team will call you back shortly."

6. **Wrap-Up**
   - "Is there anything else I can help you with today?"
   - If yes: handle the new item.
   - If no: "Thank you for calling {company}. Have a great day. Goodbye."

---

## AFTER-HOURS CALL FLOW

When a call comes in outside of business hours:

1. **Greeting**
   - "Thank you for calling {company}. Our office is currently closed. I'm Clara, and I'm here to help with urgent matters."

2. **Understand Purpose**
   - "Can you briefly tell me what you're calling about?"
   - Listen carefully to determine if it is an emergency.

3. **Determine Emergency Status**
   - Ask if unclear: "Is this an emergency situation that requires immediate attention tonight?"

4. **If EMERGENCY** (caller confirms or situation matches emergency definition):
   a. "I understand — let me get your information right away."
   b. Collect immediately (in order):
      - Full name
      - Best callback number
      - Property address
   c. "Thank you. I'm connecting you with our emergency dispatch now. Please hold."
   d. Attempt transfer to: {primary} at {primary_phone}
   e. If no answer after {timeout} seconds, attempt: {secondary} at {secondary_phone}
   f. **If all transfers fail:**
      - "I wasn't able to reach our on-call team directly, but I've logged your emergency and {fallback}. Please stay on the line or call back if the situation worsens."
   g. Wrap-up: "Is there anything else urgent I can help with?"

5. **If NON-EMERGENCY** (after hours):
   a. "I understand. Since our office is closed, I'll take your information and make sure someone follows up with you first thing during business hours."
   b. Collect: name, callback number, brief description of the issue.
   c. Confirm: "I've noted your request. Someone will call you back when the office opens at {start} {tz}."
   d. "{ner_after}"
   e. Wrap-up: "Is there anything else I can help you with?"
   f. Close: "Thank you for calling {company}. Goodbye."

---

## TRANSFER PROTOCOL (Internal)
- Initiate warm transfer when transferring during business hours if possible.
- For after-hours emergency: cold transfer is acceptable.
- Transfer timeout: {timeout} seconds before declaring failure.
- On failure: do NOT hang up abruptly. Always confirm caller information and assure follow-up.
- Never tell the caller a transfer "failed" — say "I wasn't able to reach them directly."

## FALLBACK PROTOCOL
If all routing attempts fail:
1. Confirm caller's name and number.
2. Confirm the issue was logged.
3. State expected callback timeframe.
4. Apologize once, briefly and sincerely.
5. Close the call.

## GENERAL RULES
- Never ask more than 2 questions in a row without acknowledging the caller's situation.
- Never mention internal tools, function calls, or system names.
- Never promise a specific technician will call — say "a member of our team."
- Always confirm collected information back to the caller before ending the call.
- Stay on brand: professional, warm, efficient.
"""
    return prompt.strip()


# ── Agent spec builder ─────────────────────────────────────────────────────────

def build_agent_spec(memo: dict, version: str) -> dict:
    bh = memo.get("business_hours") or {}
    er = memo.get("emergency_routing_rules") or {}
    ctr = memo.get("call_transfer_rules") or {}

    system_prompt = build_system_prompt(memo)

    spec = {
        "agent_name": f"Clara – {memo.get('company_name', 'Unknown Company')}",
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "account_id": memo.get("account_id"),
        "voice_style": {
            "gender": "female",
            "tone": "professional_warm",
            "speed": "normal",
            "notes": "Clear, calm, empathetic. Slight warmth without being overly casual."
        },
        "system_prompt": system_prompt,
        "key_variables": {
            "timezone": bh.get("timezone"),
            "business_hours_start": bh.get("start"),
            "business_hours_end": bh.get("end"),
            "business_days": bh.get("days"),
            "office_address": memo.get("office_address"),
            "emergency_primary_phone": er.get("primary_phone"),
            "emergency_secondary_phone": er.get("secondary_phone"),
            "transfer_timeout_seconds": ctr.get("timeout_seconds", 30),
        },
        "tool_invocation_placeholders": {
            "note": "All tool calls are internal and must never be mentioned to the caller.",
            "tools": [
                {
                    "name": "transfer_call",
                    "trigger": "Emergency confirmed or service routing required",
                    "params": ["destination_phone", "caller_name", "caller_phone", "issue_summary"]
                },
                {
                    "name": "log_callback_request",
                    "trigger": "Non-emergency after hours or transfer failure",
                    "params": ["caller_name", "caller_phone", "issue_summary", "property_address", "urgency"]
                },
                {
                    "name": "check_business_hours",
                    "trigger": "At call start to determine flow",
                    "params": ["current_timestamp", "timezone"]
                }
            ]
        },
        "call_transfer_protocol": {
            "timeout_seconds": ctr.get("timeout_seconds", 30),
            "retries": ctr.get("retries", 1),
            "warm_transfer": ctr.get("warm_transfer", True),
            "transfer_fail_action": "log_and_assure_callback",
            "transfer_fail_script": ctr.get(
                "transfer_fail_message",
                "I wasn't able to reach our team directly right now. I've logged your information and someone will call you back shortly."
            )
        },
        "fallback_protocol": {
            "steps": [
                "Confirm caller name and phone number",
                "Confirm issue has been logged",
                "State expected callback timeframe",
                "Brief, sincere apology",
                "Close call professionally"
            ],
            "max_retry_attempts": 2,
            "escalation_after_failure": er.get("fallback")
        },
        "retell_import_instructions": {
            "note": "To import manually into Retell UI:",
            "steps": [
                "1. Go to Retell dashboard -> Agents -> Create New Agent",
                "2. Set agent name to the 'agent_name' value above",
                "3. Paste the 'system_prompt' into the System Prompt field",
                "4. Configure voice settings per 'voice_style'",
                "5. Set up call transfer tool with phone numbers from 'key_variables'",
                "6. Set transfer timeout from 'call_transfer_protocol.timeout_seconds'",
                "7. Save and test with a test call"
            ]
        }
    }
    return spec


# ── Save ───────────────────────────────────────────────────────────────────────

def save_agent_spec(spec: dict, account_id: str, version: str) -> Path:
    out_dir = OUTPUTS_DIR / account_id / version
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "agent_spec.json"
    path.write_text(json.dumps(spec, indent=2))
    print(f"[save] Agent spec saved: {path}")
    return path


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Clara Answers – Agent Spec Generator")
    parser.add_argument("--memo", required=True, help="Path to account_memo.json")
    parser.add_argument("--account_id", required=True)
    parser.add_argument("--version", required=True, choices=["v1", "v2"])
    args = parser.parse_args()

    memo = json.loads(Path(args.memo).read_text())
    spec = build_agent_spec(memo, args.version)
    save_agent_spec(spec, args.account_id, args.version)
    print(f"\n✅ Agent spec ({args.version}) generated for {args.account_id}")


if __name__ == "__main__":
    main()
