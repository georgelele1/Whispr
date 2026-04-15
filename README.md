# Whispr

A macOS menu bar app that transcribes your voice, cleans it up with AI, and pastes the result directly into whatever app you're using — instantly.

---

## What it does

Press a hotkey → speak → press stop → Whispr transcribes, cleans, and pastes your words into the active app. No typing required.

Beyond basic transcription, Whispr understands **what you're trying to do**:

- **Dictation / email / notes** → cleans fillers, fixes punctuation, formats for the active app
- **Calendar questions** → reads your Mac Calendar and answers ("what do I have tomorrow?", "when is my COMP9417 exam?")
- **Knowledge questions** → answers factual questions inline ("what's the formula for kinetic energy?")

---

## Requirements

- macOS 13 or later
- Python 3.10+ (bundled with the app)
- Microphone access
- Calendar access (for calendar features)
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

macOS will prompt for three permissions — all are required:

| Permission | Why |
|---|---|
| **Microphone** | Recording your voice |
| **Accessibility** | Global hotkeys + auto-paste |
| **Calendars** | Reading Mac Calendar for schedule queries |

You can also grant Calendar access manually from the sidebar: **Settings → Calendar → Grant Access**.

---

## Usage

### Starting and stopping a recording

| Action | Hotkey |
|---|---|
| Start recording | `⌥ Space` |
| Stop recording | `⌥ S` |

After stopping, Whispr transcribes your audio, processes it, and pastes the result into the app that was active when you pressed start.

### Intent detection — Whispr picks the right mode automatically

You don't need to tell Whispr what you want. It detects intent from your words:

**Refine (default)** — cleaning up dictation
> *"uh so basically I wanted to say that the deadline has been moved to Friday"*
> → `The deadline has been moved to Friday.`

**Calendar** — schedule queries
> *"what do I have on tomorrow?"*
> → `Schedule for tomorrow: - 09:00 AM: COMP9417 Lecture [University] - 2:00 PM: Team standup [Work]`

> *"when is my dentist appointment?"*
> → searches your Mac Calendar and returns the matching event

**Knowledge** — factual questions
> *"what is Newton's second law?"*
> → `F = ma. Force equals mass times acceleration. F is force (N), m is mass (kg), a is acceleration (m/s²).`

---

## Features

### Personal Dictionary
Teach Whispr how to spell your names, course codes, and jargon so they're never mishear again.

- Open **Whispr → Dictionary**
- Add a **correct phrase** (e.g. `COMP9900`) and **aliases** (e.g. `comp 9900, comp9900`)
- Whispr applies corrections before every transcription — no LLM call needed

### Voice Snippets
Map a trigger phrase to any text or URL expansion.

- Open **Whispr → Snippets**
- Add a **trigger** (e.g. `zoom link`) and **expansion** (e.g. `https://zoom.us/j/123456`)
- Say the trigger during dictation — it gets expanded in the output automatically

### Mac Calendar Integration
Whispr reads directly from the Mac Calendar app — no Google sign-in, no API keys.

Any calendar synced to Mac Calendar works: iCloud, Google (via Mac Calendar sync), Exchange, etc.

Grant access once via **Settings → Calendar → Grant Access** or via the menu bar icon.

### Output Language
Whispr can transcribe and output in any supported language regardless of what language you speak.

Change it from:
- **Sidebar → Output Language** picker
- **Menu bar icon → Output Language** submenu

Supported languages: English, Chinese, Spanish, French, Japanese, Korean, Arabic, German, Portuguese.

### AI Profile Learning
After every 50 transcriptions, Whispr quietly analyses your usage patterns in the background and updates a personal profile — your career area, writing style, frequent apps, and recurring topics. This makes every subsequent transcription more accurate for your context. No data leaves your machine.

---

## Menu Bar

Click the menu bar icon (🎙) for quick access:

| Item | Description |
|---|---|
| Status | Current state: Idle / Recording / Processing / Error |
| Current App | The app that will receive pasted text |
| Last Result | Preview of the most recent transcription |
| Start / Stop Recording | Same as hotkeys |
| Output Language | Submenu to switch language |
| Update Dictionary | Trigger a background dictionary refresh from recent transcriptions |
| Calendar Access | Shows permission status; tap to grant if not yet approved |
| Open Whispr | Opens the main window |
| Quit Whispr | Exits the app |

---

## Main Window

### Home
Overview of your stats (dictionary terms, snippets, today's recordings) and a feed of recent transcriptions grouped by date. Each entry has a copy button.

### History
Full transcription history — searchable by output text or app name. Click any entry to see the raw transcription vs the cleaned output side by side. History can be cleared from here or from Settings.

### Dictionary
View, add, edit, and delete your personal dictionary terms and their aliases.

### Snippets
View, add, edit, and delete your voice snippet shortcuts.

---

## Settings (sidebar)

| Setting | Description |
|---|---|
| Hotkeys | Display of current Start / Stop shortcuts (hardcoded in `HotkeyManager.swift`) |
| Output Language | Picker — synced to backend immediately |
| Calendar | Permission status + Grant Access / Open Settings button |
| Data Management | Clear history, dictionary, snippets, or profile individually — or Reset All |

---

## Project Structure

```
whispr/
├── mac-app/
│   ├── Whispr.xcodeproj
│   └── Sources/
│       ├── AppManager.swift          # Core orchestrator
│       ├── AudioRecorder.swift       # AVFoundation recording
│       ├── LocalBackendClient.swift  # Swift ↔ Python bridge
│       ├── HotkeyManager.swift       # Global hotkeys via CGEvent
│       ├── MenuBarController.swift   # Menu bar icon + menu
│       ├── Mainwindowcontroller.swift # Main window + sidebar
│       ├── FloatingIndicator.swift   # HUD panel (recording state)
│       ├── HomeView.swift
│       ├── HistoryView.swift
│       ├── DictionaryView.swift
│       ├── SnippetsView.swift
│       ├── OnboardingView.swift
│       ├── LanguageManager.swift
│       ├── Config.swift
│       ├── Models.swift
│       └── BackendResponse.swift
└── backend/
    ├── app.py                        # Main pipeline orchestrator
    ├── gcalendar.py                  # Mac Calendar (EventKit) integration
    ├── storage.py                    # JSON storage helpers
    ├── snippets.py                   # Snippet CRUD
    ├── requirements.txt
    └── agents/
        ├── intent.py                 # Intent detection (calendar / knowledge / refine)
        ├── refiner.py                # Transcription cleaning subagent
        ├── knowledge.py              # Knowledge Q&A subagent
        ├── cal_agent.py              # Calendar fetch/search subagent
        ├── profile.py                # User profile + background learning
        ├── dictionary_agent.py       # Dictionary management
        └── plugins/
            ├── session.py            # Rolling session memory
            ├── lang.py               # Language injection
            ├── visibility.py         # Agent timing logs
            └── eval.py               # Output eval + retry loop
```

---

## Changing Hotkeys

Hotkeys are set in `HotkeyManager.swift`:

```swift
private let startHotkey = KeyCombo(keyCode: 49, modifiers: [.option])  // ⌥ Space
private let stopHotkey  = KeyCombo(keyCode: 1,  modifiers: [.option])  // ⌥ S
```

Common key codes: `Space=49`, `S=1`, `R=15`, `A=0`. Modifiers: `.option`, `.command`, `.control`, `.shift`.

---

## Data & Privacy

- All processing happens **on-device**. No audio or transcriptions are sent to external servers.
- The AI models run via your configured backend (connectonion).
- Calendar data is read locally via Mac Calendar — no Google OAuth required.
- All user data is stored in `~/Library/Application Support/Whispr/`.

---

## Troubleshooting

**Hotkeys not working**
Go to System Settings → Privacy & Security → Accessibility and make sure Whispr is enabled.

**Calendar not reading events**
Go to System Settings → Privacy & Security → Calendars and enable Whispr. Or use **Settings → Calendar → Grant Access** inside the app.

**Transcription returns empty**
Check that the microphone is not muted and Whispr has microphone permission in System Settings → Privacy & Security → Microphone.

**Backend not found**
Ensure `requirements.txt` packages are installed and the Python venv is correctly bundled inside the app's resources at `runtime/venv/bin/python`.
