# Clara Answers – Automation Pipeline

> Converts demo & onboarding call transcripts into versioned Retell AI agent configurations.  
> **Zero-cost. Reproducible. Batch-capable.**

---

## Architecture

```
clara_calls/                                  (drop audio/video here)
  BEN001_demo.m4a  ──┐
                     ├── scripts/ingest.py ── Whisper ── transcript.txt
                     │
dataset/             │
  ACC001/            │
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
                                                    │
                       ──── Retell Sync ──► retell_registry.json (live agents)
```

### Data Flow

1. **Audio Ingest** — drop audio/video files into `clara_calls/`, Whisper transcribes locally (free)
2. **Ingest** — transcript `.txt` files are saved per account into `dataset/`
3. **Extraction (Pipeline A)** — rule-based or LLM extraction produces `account_memo.json` v1
4. **Agent Spec Generation** — `account_memo` drives prompt template → `agent_spec.json` v1
5. **Onboarding Patch (Pipeline B)** — onboarding transcript applies a diff-patch to v1 → produces v2
6. **Changelog** — field-level diff between v1 and v2 is written as `changelog.json` + `changelog.md`
7. **Retell Sync** — agent specs are pushed to Retell AI via API
8. **Dashboard** — static HTML dashboard embeds all outputs for review

---

## Quick Start

### Requirements
- Python 3.10+
- No external packages needed for zero-cost mode
- `openai-whisper` for audio transcription (optional, `pip install openai-whisper`)

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

Set your Gemini API key for higher-quality extraction:

```bash
export GEMINI_API_KEY=your-key-here
python scripts/run_pipeline.py --dataset_dir ./dataset
```

> **Zero-cost note**: Gemini API has a free tier at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).  
> The `run_demo.py` rule-based extractor requires no API key at all.

---

## Adding New Accounts (Audio Ingest)

Drop audio or video call recordings into the `clara_calls/` folder and the pipeline handles everything automatically — transcription, extraction, agent spec generation, and Retell sync.

### Setup (one-time)

```bash
pip install openai-whisper
```

### File Naming Convention

The filename tells the pipeline which account to process and which stage to run. Format: `ACCOUNTID_STAGE.extension`

| Filename | Account | Stage | What Happens |
|---|---|---|---|
| `BEN001_demo.m4a` | BEN001 | demo | Pipeline A: transcribe → extract memo (v1) → generate agent spec (v1) |
| `BEN001_onboarding.m4a` | BEN001 | onboarding | Pipeline B: transcribe → patch memo (v2) → generate spec (v2) → changelog |
| `ACC002_demo.mp4` | ACC002 | demo | Pipeline A for ACC002 |
| `ACC002_onboarding.wav` | ACC002 | onboarding | Pipeline B for ACC002 |

- `ACCOUNTID` = any alphanumeric ID (e.g. `BEN001`, `CLIENT042`)
- `STAGE` = `demo` (first call) or `onboarding` (follow-up call)
- Demo must be processed before onboarding for each account
- Supported audio/video formats: `.m4a`, `.mp3`, `.mp4`, `.wav`, `.ogg`, `.flac`, `.webm`

### How to Use

**Option 1: Folder watcher (recommended)**

Start the watcher once, then drop files in anytime:

```bash
export $(cat .env | grep -v '#' | xargs)
python scripts/ingest.py --watch ./clara_calls/ --sync-retell
```

Then just download a call recording, rename it (e.g. `BEN001_demo.m4a`), and move it into `clara_calls/`. The watcher picks it up within 3 seconds and runs the full pipeline automatically.

**Option 2: Single file**

Process one file directly without the watcher:

```bash
python scripts/ingest.py --file path/to/recording.m4a --account_id BEN001 --stage demo
python scripts/ingest.py --file path/to/recording.m4a --account_id BEN001 --stage onboarding --sync-retell
```

### Pipeline Processing Flow

```
1. File dropped in clara_calls/
   ↓
2. Whisper transcribes audio → saves transcript to dataset/ACCOUNTID/demo_transcript.txt
   ↓
3. Pipeline A (demo) or Pipeline B (onboarding) runs:
   - Extracts structured account memo (company, services, contacts, routing rules)
   - Generates Retell agent spec (system prompt, voice config, tools)
   - If onboarding: diffs v1 → v2 and writes changelog
   ↓
4. If --sync-retell: pushes agent to Retell AI via API
   ↓
5. Dashboard auto-rebuilds with new account data
```

### Whisper Model Options

Use `--model` to trade speed for accuracy:

| Model | Speed | Accuracy | Best For |
|---|---|---|---|
| `tiny` | fastest | lower | quick tests |
| `base` (default) | fast | good | most recordings |
| `small` | moderate | better | noisy audio |
| `medium` | slow | best | long or complex calls |

```bash
python scripts/ingest.py --watch ./clara_calls/ --model small --sync-retell
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
  retell_registry.json         ← Synced Retell agent/LLM IDs
  logs/
    run_YYYYMMDD_HHMMSS.json   ← Batch run summary
    ingested.json              ← Audio ingest history
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
| `GEMINI_API_KEY` | No | Google Gemini key for LLM-enhanced extraction. Free at aistudio.google.com |
| `RETELL_API_KEY` | No | Retell AI key for agent sync. Enables `--sync-retell` in ingest |

| `N8N_PORT` | No | n8n port (default: 5678) |
| `CLARA_API_PORT` | No | Local API port (default: 5001) |

Copy `.env.example` to `.env` and fill in values.

---

## Scripts Reference

| Script | Purpose |
|---|---|
| `scripts/ingest.py` | **Audio ingest** — transcribe + auto-pipeline + Retell sync, folder watcher |
| `scripts/run_demo.py` | **Main batch runner** — processes all accounts, zero-cost |
| `scripts/run_pipeline.py` | Batch runner with LLM support |
| `scripts/extract_account_memo.py` | Single-account extraction CLI |
| `scripts/generate_agent_spec.py` | Agent spec generator from memo |
| `scripts/generate_changelog.py` | Diff and changelog generator |
| `scripts/retell_sync.py` | Push agent specs to Retell AI via API |
| `scripts/api_server.py` | Local HTTP API for n8n integration |
| `scripts/build_dashboard.py` | Regenerates `outputs/dashboard.html` |

---

## Known Limitations

1. **Rule-based extraction** (zero-cost mode) uses regex patterns. Complex or ambiguous transcripts may miss nuance. LLM mode (`GEMINI_API_KEY` set) significantly improves accuracy.

2. **Phone number extraction** maps by position in transcript, not by semantic role. In transcripts where multiple numbers appear without clear role labels, manual review of `emergency_routing_rules` is recommended.

3. **Whisper model size** — the default `base` model balances speed and accuracy. For longer or noisy recordings, use `--model small` or `--model medium` for better results (slower).

4. **Retell API** — free tier has limited credits ($10). The `agent_spec.json` is also a complete manual import document if API credits run out.

5. **Task tracker (Asana)** — free tier has API access, but requires OAuth setup. The pipeline logs to a local `tasks.json` by default. To enable Asana: swap the task-logging node in the n8n workflow for the Asana node and provide your API key.

---

## What Would Be Improved With Production Access

- **LLM extraction for all accounts** — better handling of ambiguous routing, multi-contact escalation chains, and partial data
- **Retell API integration** — auto-create and version agents via API instead of manual import
- **Asana/Linear task creation** — auto-create onboarding tasks with pre-filled account data
- **Real-time webhook triggers** — Zapier/Make triggers on new Calendly recordings or form submissions
- **Deepgram/cloud transcription** — alternative to local Whisper for faster processing on large files
- **Conflict resolution UI** — when onboarding contradicts demo, surface for human review
- **Multi-org support** — namespaced accounts with team access controls
