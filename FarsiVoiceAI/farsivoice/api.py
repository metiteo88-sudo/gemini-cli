"""HTTP API (replaces backend/main.py).

Run:  uvicorn farsivoice.api:app --host 0.0.0.0 --port 8000
"""

import os
import uuid
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import config
from .engines import EngineError
from .pipeline import prepare_text, text_to_voice

app = FastAPI(title="FarsiVoiceAI")
os.makedirs(config.OUTPUT_DIR, exist_ok=True)


class TextRequest(BaseModel):
    text: str
    engine: Optional[str] = None
    voice: Optional[str] = None
    rate: Optional[str] = None
    pitch: Optional[str] = None
    diacritize: bool = False


async def _generate(text: str, engine=None, diacritize=False, **opts) -> dict:
    ext = ".wav" if (engine or config.DEFAULT_ENGINE) == "piper" else ".mp3"
    filename = f"voice_{uuid.uuid4().hex}{ext}"
    path = os.path.join(config.OUTPUT_DIR, filename)
    try:
        await text_to_voice(text, path, engine=engine, diacritize=diacritize, **opts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except EngineError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {
        "text": prepare_text(text),
        "audio_file": filename,
        "audio_url": f"/audio/{filename}",
        "message": "صدا ساخته شد",
    }


@app.get("/")
def home():
    return {"message": "FarsiVoice AI آماده است"}


@app.post("/text")
async def from_text(req: TextRequest):
    return await _generate(req.text, engine=req.engine, diacritize=req.diacritize,
                           voice=req.voice, rate=req.rate, pitch=req.pitch)


@app.post("/file")
async def from_file(file: UploadFile = File(...), engine: Optional[str] = None):
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="فایل باید متنی و با کدگذاری UTF-8 باشد")
    return await _generate(text, engine=engine)


@app.get("/audio/{filename}")
def get_audio(filename: str):
    path = os.path.join(config.OUTPUT_DIR, os.path.basename(filename))
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="فایل پیدا نشد")
    return FileResponse(path)
