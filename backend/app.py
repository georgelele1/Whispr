from fastapi import FastAPI, UploadFile, File
from pathlib import Path
import shutil
import uuid
from connectonion import transcribe  # adjust if different import

app = FastAPI()

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix or ".wav"
    save_path = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"

    with save_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    # 🔥 Run speech-to-text
    result = transcribe(str(save_path))

    return {
        "text": result
    }