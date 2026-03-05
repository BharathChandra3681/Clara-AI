# Clara Answers – Automation Pipeline

> Converts demo & onboarding call transcripts into versioned Retell AI agent configurations.  
> **Zero-cost. Reproducible. Batch-capable.**

---

## Architecture

```
dataset/
  ACC001/
    demo_transcript.txt        ──┐
    onboarding_transcript.txt  ──┤
  ACC002/ ...                    │
                                 ▼
  scripts/run_demo.py  ──── Pipeline A ──► outputs/ACC001/v1/account_memo.json
                                           outputs/ACC001/v1/agent_spec.json
                       ──── Pipeline B ──► outputs/ACC001/v2/account_memo.json
                                           outputs/ACC001/v2/agent_spec.json
                                           outputs/ACC001/changelog.json
                                           outputs/ACC001/changelog.md
```

### Data Flow

1. **Ingest** — transcript `.txt` files are read per account from `dataset/`
2. **Extraction (Pipeline A)** — rule-based or LLM extraction produces `account_memo.json` v1
3. **Agent Spec Generation** — `account_memo` drives prompt template → `agent_spec.json` v1
4. **Onboarding Patch (Pipeline B)** — onboarding transcript applies a diff-patch to v1 → produces v2
5. **Changelog** — field-level diff between v1 and v2 is written as `changelog.json` + `changelog.md`
6. **Dashboard** — static HTML dashboard embeds all outputs for review

---

## Quick Start

### Requirements
- Python 3.10+
- No external packages needed for zero-cost mode

```bash
git clone <your-repo>
cd clara-pipeline

# Run full pipeline on all 5 accounts (zero-cost, no API key needed)
python scripts/run_demo.py

# View dashboard
open outputs/dashboard.html   # macOS
xdg-open outputs/dashboard.html  # Linux
```

### Optional: LLM-Enhanced Mode (better extraction quality)

Set your Anthropic API key to use `claude-haiku-4-5` for extraction:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python scripts/run_pipeline.py --dataset_dir ./dataset
```

> **Zero-cost note**: Anthropic's free tier allows limited API usage.  
> The `run_demo.py` rule-based extractor requires no API key at all.

---

## Plugging In Your Dataset

### Option A: Directory structure (auto-discovery)

```
dataset/
  YOUR_ACCOUNT_ID/
    demo_transcript.txt
    onboarding_transcript.txt   ← optional
```

### Option B: Manifest file

Edit `dataset/manifest.json`:

```json
[
  {
    "account_id": "CLIENT001",
    "demo_transcript": "CLIENT001/demo.txt",
    "onboarding_transcript": "CLIENT001/onboarding.txt"
  }
]
```

Then run:

```bash
python scripts/run_demo.py
# or with LLM:
python scripts/run_pipeline.py --dataset_dir ./dataset
```

### Transcript format

Plain text `.txt` files. No special format required.  
If using audio recordings, first transcribe with [Whisper](https://github.com/openai/whisper):

```bash
pip install openai-whisper
whisper recording.mp3 --model base --output_format txt
```

---

## Output Structure

```
outputs/
  accounts/
    ACC001/
      v1/
        account_memo.json      ← Extracted from demo call
        agent_spec.json        ← Retell agent draft (v1)
      v2/
        account_memo.json      ← Updated from onboarding
        agent_spec.json        ← Retell agent draft (v2, production-ready)
      changelog.json           ← Structured field-level diff
      changelog.md             ← Human-readable diff
  logs/
    run_YYYYMMDD_HHMMSS.json   ← Batch run summary
  dashboard.html               ← Visual dashboard
```

---

## n8n Workflow Setup

### Docker (recommended)

```bash
docker-compose up -d
```

This starts:
- n8n at `http://localhost:5678`
- Clara API server at `http://localhost:5001`

### Import workflow

1. Open n8n: `http://localhost:5678`
2. Create new workflow
3. Click ⋮ → Import from file
4. Select `workflows/clara_pipeline_n8n.json`
5. Set environment variables (see `.env.example`)
6. Activate

### Webhook endpoints (after activation)

- **Pipeline A**: `POST http://localhost:5678/webhook/clara-demo-input`
- **Pipeline B**: `POST http://localhost:5678/webhook/clara-onboarding-input`

Payload format:
```json
{
  "account_id": "ACC001",
  "transcript_text": "Full transcript text here..."
}
```

---

## Retell Agent Import

Clara generates a `agent_spec.json` per account. To import into Retell:

1. Log in to [Retell Dashboard](https://beta.retellai.com)
2. Go to **Agents** → **Create New Agent**
3. Set **Agent Name** from `agent_name` field
4. Paste `system_prompt` into the System Prompt field
5. Configure voice: Female, professional, normal speed
6. Add **Call Transfer** tool with:
   - Primary phone: `key_variables.emergency_primary_phone`
   - Timeout: `call_transfer_protocol.timeout_seconds`
7. Save and test

> **If Retell doesn't allow programmatic agent creation on free tier**, the spec JSON is the full handoff document for manual import. All fields map 1:1 to Retell UI fields.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | No | Enables LLM extraction. If not set, uses rule-based extraction. |
| `N8N_PORT` | No | n8n port (default: 5678) |
| `CLARA_API_PORT` | No | Local API port (default: 5001) |

Copy `.env.example` to `.env` and fill in values.

---

## Scripts Reference

| Script | Purpose |
|---|---|
| `scripts/run_demo.py` | **Main batch runner** — processes all accounts, zero-cost |
| `scripts/run_pipeline.py` | Batch runner with LLM support |
| `scripts/extract_account_memo.py` | Single-account extraction CLI |
| `scripts/generate_agent_spec.py` | Agent spec generator from memo |
| `scripts/generate_changelog.py` | Diff and changelog generator |
| `scripts/api_server.py` | Local HTTP API for n8n integration |
| `scripts/build_dashboard.py` | Regenerates `outputs/dashboard.html` |

---

## Known Limitations

1. **Rule-based extraction** (zero-cost mode) uses regex patterns. Complex or ambiguous transcripts may miss nuance. LLM mode (`ANTHROPIC_API_KEY` set) significantly improves accuracy.

2. **Phone number extraction** maps by position in transcript, not by semantic role. In transcripts where multiple numbers appear without clear role labels, manual review of `emergency_routing_rules` is recommended.

3. **No audio transcription** included in the pipeline. If your dataset is audio-only, run Whisper first (free, open-source).

4. **Retell API** — free tier does not support programmatic agent creation. The `agent_spec.json` is a complete manual import document.

5. **Task tracker (Asana)** — free tier has API access, but requires OAuth setup. The pipeline logs to a local `tasks.json` by default. To enable Asana: swap the task-logging node in the n8n workflow for the Asana node and provide your API key.

---

## What Would Be Improved With Production Access

- **LLM extraction for all accounts** — better handling of ambiguous routing, multi-contact escalation chains, and partial data
- **Retell API integration** — auto-create and version agents via API instead of manual import
- **Asana/Linear task creation** — auto-create onboarding tasks with pre-filled account data
- **Real-time webhook triggers** — Zapier/Make triggers on new Calendly recordings or form submissions
- **Audio pipeline** — auto-transcribe with Whisper or Deepgram before extraction
- **Conflict resolution UI** — when onboarding contradicts demo, surface for human review
- **Multi-org support** — namespaced accounts with team access controls
