from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Optional

import soundfile as sf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
OUTPUT_DIR = Path(os.getenv("VOXCPM_OUTPUT_DIR", BASE_DIR / "outputs")).resolve()
MODEL_ID = os.getenv("VOXCPM_MODEL", "openbmb/VoxCPM2")
DEVICE = os.getenv("VOXCPM_DEVICE", "auto")
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
ALLOWED_SUFFIXES = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".webm"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("voxcpm-web")


class ModelState:
    model = None
    error: Optional[str] = None
    lock = asyncio.Lock()


state = ModelState()


def load_model():
    if state.model is not None:
        return state.model
    try:
        from voxcpm import VoxCPM

        logger.info("Loading VoxCPM model %s on %s", MODEL_ID, DEVICE)
        state.model = VoxCPM.from_pretrained(MODEL_ID, device=DEVICE)
        state.error = None
        logger.info("VoxCPM model is ready")
        return state.model
    except Exception as exc:
        state.error = str(exc)
        logger.exception("Unable to load VoxCPM")
        raise


@asynccontextmanager
async def lifespan(_: FastAPI):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Deliberately lazy-load: the web server can start and expose a useful status
    # response even if CUDA/model configuration needs attention.
    yield


app = FastAPI(title="VoxCPM2 Studio", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
async def status():
    return {
        "ready": state.model is not None,
        "loading": state.lock.locked() and state.model is None,
        "model": MODEL_ID,
        "device": DEVICE,
        "error": state.error,
    }


def _safe_control(control: str) -> str:
    return re.sub(r"[()（）]", "", control).strip()


async def _save_upload(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "reference.wav").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, "參考音檔格式不支援")

    destination = Path(tempfile.gettempdir()) / f"voxcpm-ref-{uuid.uuid4().hex}{suffix}"
    total = 0
    try:
        with destination.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "參考音檔不可超過 30 MB")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    return destination


@app.post("/api/generate")
async def generate(
    text: Annotated[str, Form(min_length=1, max_length=2000)],
    mode: Annotated[str, Form()] = "design",
    control: Annotated[str, Form(max_length=500)] = "",
    prompt_text: Annotated[str, Form(max_length=2000)] = "",
    cfg_value: Annotated[float, Form(ge=1.0, le=3.0)] = 2.0,
    inference_timesteps: Annotated[int, Form(ge=1, le=50)] = 10,
    normalize: Annotated[bool, Form()] = False,
    denoise: Annotated[bool, Form()] = False,
    seed: Annotated[Optional[int], Form(ge=0, le=2147483647)] = None,
    reference_audio: Annotated[Optional[UploadFile], File()] = None,
):
    text = text.strip()
    if not text:
        raise HTTPException(400, "請輸入要合成的文字")
    if mode not in {"design", "clone", "ultimate"}:
        raise HTTPException(400, "未知的生成模式")
    if mode in {"clone", "ultimate"} and reference_audio is None:
        raise HTTPException(400, "此模式需要參考音檔")
    if mode == "ultimate" and not prompt_text.strip():
        raise HTTPException(400, "極致複製需要參考音檔的逐字稿")

    reference_path: Optional[Path] = None
    try:
        if reference_audio is not None:
            reference_path = await _save_upload(reference_audio)

        final_text = text
        cleaned_control = _safe_control(control)
        if mode != "ultimate" and cleaned_control:
            final_text = f"({cleaned_control}){text}"

        kwargs = {
            "text": final_text,
            "cfg_value": cfg_value,
            "inference_timesteps": inference_timesteps,
            "normalize": normalize,
            "denoise": denoise,
        }
        if seed is not None:
            kwargs["seed"] = seed
        if reference_path is not None:
            kwargs["reference_wav_path"] = str(reference_path)
        if mode == "ultimate":
            kwargs["prompt_wav_path"] = str(reference_path)
            kwargs["prompt_text"] = prompt_text.strip()

        async with state.lock:
            try:
                model = await asyncio.to_thread(load_model)
                wav = await asyncio.to_thread(model.generate, **kwargs)
                sample_rate = model.tts_model.sample_rate
            except Exception as exc:
                logger.exception("Generation failed")
                raise HTTPException(500, f"語音生成失敗：{exc}") from exc

        output_name = f"voxcpm-{uuid.uuid4().hex}.wav"
        output_path = OUTPUT_DIR / output_name
        await asyncio.to_thread(sf.write, output_path, wav, sample_rate)
        return {
            "audio_url": f"/api/audio/{output_name}",
            "filename": output_name,
            "sample_rate": sample_rate,
        }
    finally:
        if reference_path is not None:
            reference_path.unlink(missing_ok=True)


@app.get("/api/audio/{filename}")
async def audio(filename: str):
    if not re.fullmatch(r"voxcpm-[0-9a-f]{32}\.wav", filename):
        raise HTTPException(404)
    path = OUTPUT_DIR / filename
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="audio/wav", filename=filename)


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="VoxCPM2 browser interface")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8808)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
