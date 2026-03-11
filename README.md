# Whispr – Privacy-First Local Voice-to-Text Assistant

Whispr is a **privacy-focused local speech-to-text system for macOS** that captures audio from the microphone and converts it into enhanced text using a local AI processing pipeline.

Unlike many speech transcription tools, Whispr is designed to **operate entirely locally**, ensuring that **no audio or text is transmitted to external cloud services**.

The system combines a **macOS menu-bar frontend written in Swift** with a **Python backend AI agent** that performs transcription, dictionary correction, and text enhancement.

---

# Features

- Push-to-talk voice recording from macOS menu bar
- Local speech-to-text transcription
- AI-assisted text enhancement
- Personal dictionary correction
- Context-aware text formatting
- No audio file storage (audio processed in memory)
- Fully local processing for privacy

---

# System Architecture

Whispr is composed of two major components:

### Frontend
- Swift macOS Menu Bar Application
- Handles user interaction and microphone recording
- Sends audio data to the local backend

### Backend
- Python AI agent built with **ConnectOnion**
- Performs transcription and text processing
- Applies dictionary corrections and AI enhancement

All communication occurs locally through **localhost**.

---

# Project Structure



---

# Requirements

### Backend

- Python **3.10 or 3.11**
- pip
- macOS for frontend development

---

# Backend Setup

### 1. Navigate to the backend directory

```bash
cd backend
