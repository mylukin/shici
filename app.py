import os
import asyncio
from typing import List, Optional
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import edge_tts
import uuid
import uvicorn
import utils

app = FastAPI()

# Set up templates and static files
templates = Jinja2Templates(directory="templates")
os.makedirs("static", exist_ok=True)
os.makedirs("static/audio", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Chinese voice options
CHINESE_VOICES = [
    "zh-CN-XiaoxiaoNeural",
    "zh-CN-YunxiNeural",
    "zh-CN-YunjianNeural",
    "zh-CN-XiaoyiNeural",
    "zh-CN-YunyangNeural"
]

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "voices": CHINESE_VOICES})

@app.post("/convert-text")
async def convert_text(
    text: str = Form(...), 
    voice: str = Form(DEFAULT_VOICE),
    rate: str = Form("+0%"),
    volume: str = Form("+0%"),
    pitch: str = Form("+0Hz")
):
    """Convert the provided text to speech and return the audio file path"""
    output_filename = await utils.convert_text_to_speech(text, voice, rate, volume, pitch)
    return {"audio_path": output_filename}

@app.post("/convert-file")
async def convert_file(
    file: UploadFile = File(...),
    voice: str = Form(DEFAULT_VOICE),
    rate: str = Form("+0%"),
    volume: str = Form("+0%"),
    pitch: str = Form("+0Hz"),
    segment_size: int = Form(500)
):
    """Convert a text file to multiple speech segments"""
    content = await file.read()
    text = content.decode("utf-8")
    
    # Split text into segments
    segments = [text[i:i+segment_size] for i in range(0, len(text), segment_size)]
    
    output_files = []
    for i, segment in enumerate(segments):
        output_filename = f"static/audio/segment_{i}_{uuid.uuid4()}.mp3"
        await utils.convert_text_to_speech(segment, voice, rate, volume, pitch, output_filename)
        output_files.append(output_filename)
    
    return {"audio_files": output_files}

@app.post("/process-shici")
async def process_shici(
    voice: str = Form(DEFAULT_VOICE),
    rate: str = Form("+0%"),
    volume: str = Form("+0%"),
    pitch: str = Form("+0Hz")
):
    """Process the shici.txt file by entries"""
    try:
        entries = utils.parse_shici_file("shici.txt")
        result = await utils.process_shici_entries(entries, voice, rate, volume, pitch)
        return {"status": "success", "audio_files": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/available-voices")
async def available_voices():
    """Get a list of available voices"""
    chinese_voices = await utils.get_chinese_voices()
    return {"voices": chinese_voices}

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True) 