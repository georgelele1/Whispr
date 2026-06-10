# Whispr

A macOS menu bar app that transcribes your voice, cleans it up with AI, and pastes the result directly into whatever app you're using — instantly.

---

## What it does

Press a hotkey → speak → press stop → Whispr transcribes, cleans, and pastes your words into the active app. No typing required.

Whispr understands **context** — it formats output differently based on the app you're in:

- **Mail** → complete email with subject, greeting, body, sign-off
- **Slack / Teams** → short conversational message
- **Terminal / VS Code** → infers correct shell command or code syntax automatically
- **Notes / Docs** → clean paragraphs or numbered lists
- **Any other app** → cleaned, punctuated prose

---

## Requirements

- macOS 13 or later
- Python 3.10+ (bundled with the app)
- Microphone access
- Accessibility access (for global hotkeys and auto-paste)

---

## Installation

### 1. Clone the repo

```bash
git clone https://github.com/georgelele1/Comp9900-w18c-almond.git
cd whispr
```

### 2. Install Python dependencies

Run the setup script from the repo root:

```bash
bash mac-app/envscripts/scripts.sh
```

This script will:
- Create a Python virtual environment at `mac-app/runtime/venv/`
- Install all packages from `backend/requirements.txt`
- Run a quick smoke test (`get-language`) to confirm the backend is working

If you see `Runtime setup complete.` at the end, you're good to go.

> **Note:** The script requires `python3.11`. If you have a different Python version, run it as:
> ```bash
> PYTHON_BIN=python3.12 bash mac-app/envscripts/scripts.sh
> ```

### 3. Open and build the Xcode project

```
mac-app/Whispr.xcodeproj
```

Build and run with **⌘R** in Xcode, or archive for distribution.

### 4. Grant permissions on first launch

macOS will prompt for two permissions — both are required.

> **Important:** Assign a development team in the Xcode project's **Signing & Capabilities** tab before building. Without a team, macOS treats each build as a new, unrecognised app and your granted permissions will not be saved between runs.

| Permission | Why |
|---|---|
| **Microphone** | Recording your voice |
| **Accessibility** | Global hotkeys + auto-paste |

---

## Usage

### Starting and stopping a recording

| Action | Hotkey |
|---|---|
| Start recording | `⌥ Space` |
| Stop recording | `⌥ S` |

After stopping, Whispr transcribes your audio, processes it, and pastes the result into the app that was active when you pressed start.

### How Whispr formats your output

Whispr is a transcription cleaner — it takes raw voice input and produces polished text. It automatically:

- Removes filler words (uh, um, like, so, basically)
- Fixes punctuation and capitalisation
- Formats lists when you say "first… second… third…" or use connectors like "also", "and then"
- Adapts format to the active app (email, chat, terminal, notes)
- Supports any output language regardless of what language you speak in

**Dictation examples:**

> *"uh so basically I wanted to say that the deadline has been moved to Friday"*
> → `The deadline has been moved to Friday.`

> *"point one make sure the tests pass point two update the readme point three tag the release"*
> → `1. Make sure the tests pass.`
> → `2. Update the README.`
> → `3. Tag the release.`

> *"install connectonion in my terminal"* (in Terminal)
> → `pip install connectonion`

---

## Features

### Personal Dictionary
Teach Whispr how to spell your names, course codes, package names, and jargon so they're never misheard again.

- Open **Whispr → Dictionary**
- Add a **correct phrase** (e.g. `connectonion`) and **aliases** (e.g. `connector onion, connect onion`)
- Corrections are applied before every transcription — no LLM call needed
- The dictionary also **auto-learns** from your transcription history every 5 recordings, using sentence structure analysis to extract person names, package names, and technical terms automatically

### Voice Snippets
Map a trigger phrase to any text or URL expansion.

- Open **Whispr → Snippets**
- Add a **trigger** (e.g. `zoom link`) and **expansion** (e.g. `https://zoom.us/j/123456`)
- Say the trigger during dictation — it expands in the output automatically
- Works across languages: saying the trigger in Chinese will still expand the English snippet correctly

### Output Language
Whispr can transcribe and output in any supported language regardless of what language you speak.

Change it from:
- **Menu bar icon → Output Language** submenu
- **Sidebar → Output Language** picker

Supported: English, Chinese, Spanish, French, Japanese, Korean, Arabic, German, Portuguese.

### AI Model Selection
Choose which AI model powers Whispr from the **API Keys** tab.

| Provider | Models | Key required |
|---|---|---|
| Google (via connectonion) | Gemini 3 Flash, Gemini 3 Pro, Gemini 2.5 Flash | No — included free |
| OpenAI | GPT-5.5, GPT-5, GPT-4o | Yes — paste your `sk-` key |
| Anthropic | Claude Opus 4.6, Claude Sonnet 4.6, Claude Haiku 4.5 | Yes — paste your `sk-ant-` key |

Provider is detected automatically from the key prefix when you paste it.

### AI Profile Learning
After every 50 transcriptions, Whispr quietly analyses your usage patterns and updates a personal profile — your career area, writing style, frequent apps, and recurring topics. This makes every subsequent transcription more accurate for your context. No data leaves your machine.

### Context Awareness (Session Memory)
Whispr remembers recent interactions within a 60-minute window and understands follow-up instructions like:

- "make it shorter"
- "make it more polite"
- "add one more point to it"
- "translate it"

The system automatically decides whether to use previous context or treat the input independently — no trigger words required.

---

### Agent Routing

Whispr uses a structured agent loop before text refinement:

- Calendar requests are routed to a read-only macOS Calendar agent.
- Professional document and literature requests are routed to a local Knowledge agent.
- Other requests continue through the app-aware Refiner agent.

The Knowledge agent searches TXT, Markdown, JSON, CSV, and text-based PDF files from:

- `~/Library/Application Support/Whispr/knowledge`
- `mac-app/backend/knowledge` for files bundled with the app

## Menu Bar

Click the menu bar icon for quick access:

| Item | Description |
|---|---|
| Last result | Preview of the most recent transcription (click to copy) |
| Model | Active model + cost + balance |
| Start / Stop Recording | Same as hotkeys |
| Output Language | Submenu to switch output language |
| Update Dictionary | Manually trigger a dictionary refresh from recent transcriptions |
| Settings | Opens the main window |
| Quit Whispr | Exits the app |

---

## Main Window

### Home
Overview of your stats (dictionary terms, snippets, today's recordings) and a feed of recent transcriptions grouped by date. Each entry has a copy button.

### History
Full transcription history — searchable by output text or app name. Click any entry to see the raw transcription vs the cleaned output side by side. History can be cleared from here.

### Dictionary
View, add, edit, and delete your personal dictionary terms and their aliases.

### Snippets
View, add, edit, and delete your voice snippet shortcuts.

### Shortcuts
Customise the start and stop recording hotkeys. Click a shortcut pill to record a new key combination. Requires at least one modifier key (⌘ ⌃ ⌥ ⇧).

### API Keys
Select your AI model and manage API keys per provider. Keys are stored locally in `~/Library/Application Support/Whispr/.env` — never sent anywhere else.

---

## Running the Test Suite

The test suite exercises the full backend pipeline — transcription cleaning, app-aware formatting, session memory, snippet expansion, and edge cases — without requiring audio input or a running macOS app.

### Prerequisites

Make sure the Python virtual environment is set up by running `scripts.sh` (see [Installation](#installation) step 2). The venv is linked automatically — no activation needed.

### Run all tests

From the repo root:

```bash
python mac-app/backend/testall.py
```

Or from inside the backend directory:

```bash
cd mac-app/backend
python testall.py
```

### What the suite covers

| Suite | Cases | What it checks |
|---|---|---|
| **Single-turn tests** | 9 | Filler removal, list formatting, chat/email/terminal formatting, meaning preservation, grammar |
| **Edge case tests** | 6 | Empty input, whitespace, CJK unicode, long input, filler-only input, numbers/IPs |
| **Snippet tests** | 4 | Exact trigger expansion, case-insensitive match, no false expansion, multiple snippets |
| **Session tests** | 4 | Shorten output, politeness change, add a step, language continuity across turns |

### Example output

```
================================================================================
SINGLE TURN TESTS
================================================================================

CASE : filler removal — quick_clean layer
APP  : Notes
IN   : 'uh so basically i think we should start the meeting now'
OUT  : 'I think we should start the meeting now.'
  ✅ PASS — filler removal — quick_clean layer

CASE : terminal command — all packages, no markdown
APP  : Terminal
IN   : 'install numpy pandas matplotlib'
OUT  : 'pip install numpy pandas matplotlib'
  ✅ PASS — terminal command — all packages, no markdown

...

================================================================================
FINAL RESULT
================================================================================
  Passed : 23
  Failed : 0
  Total  : 23
```

### Environment flags

Two optional flags enable extra debug output during a test run:

| Flag | Effect |
|---|---|
| `WHISPR_DEBUG_EVAL=1` | Enables the eval/retry loop — each output is scored and retried up to 2 times if it fails |
| `WHISPR_DEBUG_LOGS=1` | Prints agent timing and tool call counts to stderr after each transcription |

```bash
WHISPR_DEBUG_EVAL=1 python mac-app/backend/testall.py
```

---

## Changing Hotkeys

Use the **Shortcuts** tab in the main window to record new key combinations without editing code. Changes take effect immediately.

Defaults: `⌥ Space` to start, `⌥ S` to stop.

---

## Project Structure

```
whispr/
├── mac-app/
│   ├── Whispr.xcodeproj
│   ├── envscripts/
│   │   └── scripts.sh                    # One-command venv + dependency setup
│   ├── runtime/
│   │   └── venv/                         # Auto-created by scripts.sh
│   └── Sources/
│       ├── AppManager.swift              # Core orchestrator + auto dictionary trigger
│       ├── AudioRecorder.swift           # AVFoundation recording
│       ├── LocalBackendClient.swift      # Swift ↔ Python bridge
│       ├── HotkeyManager.swift           # Global hotkeys via CGEvent
│       ├── MenuBarController.swift       # Menu bar icon + menu
│       ├── Mainwindowcontroller.swift    # Main window + sidebar navigation
│       ├── FloatingIndicator.swift       # HUD panel (recording / processing state)
│       ├── Config.swift                  # Provider + model registry
│       ├── Models.swift                  # AppStatus enum
│       ├── LanguageManager.swift         # Output language state
│       ├── HomeView.swift
│       ├── HistoryView.swift
│       ├── DictionaryView.swift
│       ├── SnippetsView.swift
│       ├── ShortcutsView.swift
│       ├── APIKeysView.swift
│       ├── OnboardingView.swift
│       ├── OnboardingTour.swift
│       ├── WhisprTheme.swift
│       └── BackendResponse.swift
└── backend/
    ├── app.py                            # Main pipeline orchestrator
    ├── storage.py                        # JSON storage + multi-provider API key management
    ├── snippets.py                       # Snippet CRUD
    ├── testall.py                        # Full backend test suite
    └── agents/
        ├── refiner.py                    # Transcription cleaning subagent
        ├── profile.py                    # User profile + background learning
        ├── dictionary_agent.py           # Dictionary management + auto-learning
        └── plugins/
            ├── session.py                # Rolling session memory (60 min TTL)
            ├── lang.py                   # Language injection
            ├── snippets.py               # Snippet placeholder injection + restoration
            ├── visibility.py             # Agent timing logs (debug only)
            └── eval.py                   # Output eval + retry loop (debug only)
```

---

## Data & Privacy

- All processing happens **on-device**. No audio or transcriptions are sent to external servers.
- AI models run via connectonion (Google) or your own API key (OpenAI / Anthropic).
- All user data is stored in `~/Library/Application Support/Whispr/`.
- API keys are stored in `~/Library/Application Support/Whispr/.env` — local only.

---
