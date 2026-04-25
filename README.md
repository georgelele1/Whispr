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
git clone https://github.com/your-org/whispr.git
cd whispr
```

### 2. Install Python dependencies

```bash
run the script.sh in env script page
```

### 3. Open and build the Xcode project

```
mac-app/Whispr.xcodeproj
```

Build and run with **⌘R** in Xcode, or archive for distribution.

### 4. Grant permissions on first launch

macOS will prompt for two permissions — both are required:

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
> → `1. Make sure the tests pass.\n2. Update the README.\n3. Tag the release.`

> *"install connectonion in my terminal"* (in Terminal)
> → `pip install connectonion`

---

## Features

### Personal Dictionary
Teach Whispr how to spell your names, course codes, package names, and jargon so they're never misheard again.

- Open **Whispr → Dictionary**
- Add a **correct phrase** (e.g. `connectonion`) and **aliases** (e.g. `connector onion, connect onion`)
- Corrections are applied before every transcription — no LLM call needed
- The dictionary also **auto-learns** from your transcription history every 5 recordings, using sentence structure analysis (WHO and WHAT) to extract person names, package names, and technical terms automatically

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
| OpenAI | GPT-5.4, GPT-5, GPT-4o | Yes — paste your `sk-` key |
| Anthropic | Claude Opus 4.6, Claude Sonnet 4.6, Claude Haiku 4.5 | Yes — paste your `sk-ant-` key |

Provider is detected automatically from the key prefix when you paste it.

### AI Profile Learning
After every 50 transcriptions, Whispr quietly analyses your usage patterns and updates a personal profile — your career area, writing style, frequent apps, and recurring topics. This makes every subsequent transcription more accurate for your context. No data leaves your machine.

---

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

## Project Structure

```
whispr/
├── mac-app/
│   ├── Whispr.xcodeproj
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
│       ├── FloatingIndicator.swift
│       ├── WhisprTheme.swift
│       └── BackendResponse.swift
└── backend/
    ├── app.py                            # Main pipeline orchestrator
    ├── storage.py                        # JSON storage + multi-provider API key management
    ├── snippets.py                       # Snippet CRUD
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

## Changing Hotkeys

Use the **Shortcuts** tab in the main window to record new key combinations without editing code. Changes take effect immediately.

Defaults: `⌥ Space` to start, `⌥ S` to stop.

---

## Data & Privacy

- All processing happens **on-device**. No audio or transcriptions are sent to external servers.
- AI models run via connectonion (Google) or your own API key (OpenAI / Anthropic).
- All user data is stored in `~/Library/Application Support/Whispr/`.
- API keys are stored in `~/Library/Application Support/Whispr/.env` — local only.

---

## Troubleshooting

**Hotkeys not working**
Go to System Settings → Privacy & Security → Accessibility and make sure Whispr is enabled.

**Transcription returns empty**
Check that the microphone is not muted and Whispr has microphone permission in System Settings → Privacy & Security → Microphone.

**"Failed to save API key"**
Ensure the app has been built and deployed correctly so `app.py` can load without import errors. Check Xcode's debug console for Python tracebacks.

**Backend not found**
Ensure `requirements.txt` packages are installed and the Python venv is correctly bundled inside the app's resources at `runtime/venv/bin/python`.

**Dictionary not learning**
Dictionary auto-update runs every 5 transcriptions. You can also trigger it manually from Menu Bar → Update Dictionary. Check that `~/Library/Application Support/Whispr/dictionary_last_update.json` exists after the first update.
