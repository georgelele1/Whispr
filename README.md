# Whispr

Whispr is a macOS menu bar application that records speech, transcribes it, routes the resulting text through specialized AI agents, and pastes the final output into the active application.

It combines a native SwiftUI client with a local Python backend and supports context-aware text refinement, translation, macOS Calendar queries, local document retrieval, session memory, personal terminology, and voice snippets.

## Key Features

- Voice recording and transcription from a global keyboard shortcut
- App-aware text refinement for mail, chat, documents, terminals, and code editors
- Structured Agent Loop with rule-based routing and LLM fallback
- Read-only macOS Calendar queries through EventKit
- Local RAG over Markdown, text, JSON, CSV, and text-based PDF files
- Personal dictionary with automatic terminology extraction
- Voice snippet expansion with local matching and semantic fallback
- Short-term session memory for follow-up instructions
- Background profile learning from transcription history
- Configurable output language and model provider
- Local history, settings, dictionary, snippets, and knowledge files

## How It Works

```text
Audio recording
    -> Speech transcription
    -> Local cleanup and dictionary correction
    -> Intent Router
    -> Refiner / Calendar / Knowledge Agent
    -> Output evaluation
    -> Session and history update
    -> Paste into the active application
```

### Agent Loop

The backend converts each request into a structured route containing:

```text
intent
need_tool
tool_name
query
start_iso
end_iso
confidence
reason
```

Clear calendar and knowledge requests are detected locally. Ambiguous requests are classified by an LLM, with invalid or low-confidence results falling back to the Refiner Agent.

Current routes:

| Intent | Module | Purpose |
|---|---|---|
| `refine` | Refiner Agent | Cleanup, translation, email, chat, notes, commands, and code |
| `calendar` | Calendar Agent | Read events from the macOS Calendar |
| `knowledge` | Knowledge Agent | Retrieve local documents and produce grounded answers |

### Context-Aware Refinement

The Refiner Agent receives:

- Active macOS application
- Selected output language
- Recent session context
- User profile
- Personal dictionary
- Voice snippet placeholders

This allows the same spoken input to be formatted differently for Mail, Slack, Notes, Terminal, VS Code, and other applications.

### Local RAG

The Knowledge Agent searches two locations:

```text
~/Library/Application Support/Whispr/knowledge
mac-app/backend/knowledge
```

Supported formats:

```text
.txt  .md  .markdown  .json  .csv  .pdf
```

Documents are split into overlapping chunks, ranked using lightweight lexical retrieval, and limited to the top three matches and a bounded prompt context. Parsed chunks are cached until their source file changes.

PDF support requires a text layer. Scanned image-only PDFs require OCR before they can be searched.

Example:

```bash
cd mac-app/backend
python app.py cli knowledge-search "How does LoRA reduce trainable parameters?"
```

### Calendar Agent

The Calendar Agent uses EventKit to query the user's macOS Calendar. It is read-only and returns event titles, times, calendars, locations, and notes.

Calendar access must be granted under:

```text
System Settings -> Privacy & Security -> Calendars
```

### Memory and Personalization

- Session memory stores the last three exchanges and expires after 60 minutes.
- The personal dictionary applies local alias corrections before generation.
- Dictionary learning runs after every five successful transcriptions.
- Profile learning runs in a background process after approximately 50 new history records.
- Learned profile context includes recurring topics, writing preferences, and frequently used applications.

### Evaluation Pipeline

The default evaluation path uses local checks and does not make another model request. It checks for empty output, excessive output length, and residual filler words.

Set the following environment variable to enable one additional LLM judge call:

```bash
WHISPR_DEBUG_EVAL=1
```

## Requirements

### macOS Application

- macOS 13 or later
- Xcode
- Python 3.11 recommended
- Microphone permission
- Accessibility permission
- Calendar permission for Calendar Agent requests

### Model Access

The current default model is `gpt-5.5`, which requires an OpenAI API key. Model availability depends on the models enabled for your OpenAI account.

Supported configuration:

| Provider | Models | Credential |
|---|---|---|
| OpenAI | GPT-5.5, GPT-5, GPT-4o | `OPENAI_API_KEY` |
| Google through ConnectOnion | Gemini 3 Flash, Gemini 3 Pro, Gemini 2.5 Flash | `OPENONION_API_KEY` |
| Anthropic | Claude Opus, Sonnet, and Haiku variants | `ANTHROPIC_API_KEY` |

Keys entered through the application are stored in:

```text
~/Library/Application Support/Whispr/.env
```

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/georgelele1/Whispr.git
cd Whispr
```

### 2. Prepare the Python Runtime

On macOS:

```bash
bash mac-app/envscripts/scripts.sh
```

To select a different Python executable:

```bash
PYTHON_BIN=python3.12 bash mac-app/envscripts/scripts.sh
```

The script creates:

```text
mac-app/runtime/venv
```

On Windows, for backend development and tests only:

```powershell
powershell -ExecutionPolicy Bypass -File mac-app\envscripts\win_scripts.ps1
```

The SwiftUI application and EventKit integration require macOS.

### 3. Configure a Model Credential

You can use the application's API Keys screen or configure the backend environment manually.

For the default OpenAI model:

```env
OPENAI_API_KEY=your-key
```

For ConnectOnion models:

```bash
cd mac-app/backend
co init
```

Never commit `.env` files or API keys.

### 4. Build the macOS Application

Open:

```text
mac-app/Whispr/Whispr.xcodeproj
```

Assign a development team under **Signing & Capabilities**, then build and run the application from Xcode.

### 5. Grant Permissions

| Permission | Purpose |
|---|---|
| Microphone | Record speech |
| Accessibility | Global shortcuts and automatic paste |
| Calendars | Read events for Calendar Agent requests |

## Usage

Default shortcuts:

| Action | Shortcut |
|---|---|
| Start recording | `Option + Space` |
| Stop and process | `Option + S` |

The shortcuts can be changed from the Shortcuts screen.

Example dictation:

```text
Input:  "uh so basically the deadline has moved to Friday"
Output: "The deadline has moved to Friday."
```

Example follow-up:

```text
First request: "Write an email explaining that I will submit tomorrow."
Follow-up:     "Make it more polite."
```

Example calendar request:

```text
What meetings do I have tomorrow?
```

Example knowledge request:

```text
According to the local research papers, how does RAG use non-parametric memory?
```

## Application Screens

- **Home**: usage summary and recent transcription history
- **History**: searchable raw and processed transcription records
- **Dictionary**: personal terms, aliases, editing, and removal
- **Snippets**: voice trigger and expansion management
- **Shortcuts**: configurable start and stop shortcuts
- **API Keys**: model selection and provider credential management
- **Output Language**: target language selection

## Testing

### Local Unit Tests

These tests cover Agent routing, RAG retrieval and caching, profile learning thresholds, local evaluation, and snippet failure handling. They do not require a live model request.

```bash
cd mac-app/backend
python -m unittest -v test_agent_loop.py
```

Current suite: 12 tests.

### LLM Integration Tests

The integration suite exercises live refinement, app-aware formatting, and session behavior:

```bash
cd mac-app/backend
python testall.py
```

This suite requires network access and a valid credential for the selected model. Remote API latency or outages can cause transient failures.

### Syntax Check

```bash
cd mac-app/backend
python -m compileall app.py agents storage.py snippets.py
```

### Useful Backend Commands

```bash
# Inspect routing without running the selected agent
python app.py cli route "Check my calendar tomorrow" "Calendar"

# Search the local knowledge base
python app.py cli knowledge-search "transformer attention"

# Refine text without recording audio
python app.py cli refine "uh please make this more formal" "Notes" "English"

# Inspect recent history
python app.py cli get-history
```

## Project Structure

```text
Whispr/
|-- mac-app/
|   |-- Whispr/
|   |   |-- Whispr.xcodeproj/
|   |   `-- Whispr/
|   |       |-- AppManager.swift
|   |       |-- AudioRecorder.swift
|   |       |-- LocalBackendClient.swift
|   |       |-- HotkeyManager.swift
|   |       |-- MenuBarController.swift
|   |       |-- FloatingIndicator.swift
|   |       |-- Config.swift
|   |       `-- ...
|   |-- backend/
|   |   |-- app.py
|   |   |-- storage.py
|   |   |-- snippets.py
|   |   |-- testall.py
|   |   |-- test_agent_loop.py
|   |   |-- knowledge/
|   |   `-- agents/
|   |       |-- agent_loop.py
|   |       |-- refiner.py
|   |       |-- calendar_agent.py
|   |       |-- knowledge_agent.py
|   |       |-- dictionary_agent.py
|   |       |-- profile.py
|   |       `-- plugins/
|   |           |-- session.py
|   |           |-- snippets.py
|   |           |-- eval.py
|   |           |-- appname.py
|   |           `-- lang.py
|   `-- envscripts/
|       |-- scripts.sh
|       `-- win_scripts.ps1
|-- README.md
`-- RESUME_PROJECT.md
```

## Data and Privacy

- Audio files are recorded locally before transcription.
- History, profile, dictionary, snippets, session memory, and knowledge documents are stored locally.
- Calendar access is read-only.
- Knowledge retrieval and document parsing run locally.
- Requests sent to the selected LLM or transcription provider leave the device and are subject to that provider's privacy policy.
- API keys are stored locally and excluded from Git by `.gitignore`.

Default application data location:

```text
~/Library/Application Support/Whispr/
```

## Current Limitations

- The application UI requires macOS.
- Calendar integration cannot be tested on Windows.
- Local RAG currently uses lexical retrieval rather than embeddings or a vector database.
- Image-only PDFs require OCR.
- Knowledge ingestion does not yet have a dedicated frontend file manager.
- Live integration tests depend on external model availability and network connectivity.

## License

No license file is currently included. Add a license before distributing or accepting external contributions.
