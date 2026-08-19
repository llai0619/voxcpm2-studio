from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated, Optional

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
OUTPUT_DIR = Path(os.getenv("VOXCPM_OUTPUT_DIR", BASE_DIR / "outputs")).resolve()
MODEL_ID = os.getenv("VOXCPM_MODEL", "openbmb/VoxCPM2")
DEVICE = os.getenv("VOXCPM_DEVICE", "auto")
BUILD_VERSION = os.getenv("VOXCPM_BUILD", "development")
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
ALLOWED_SUFFIXES = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".webm"}
SHORT_TEXT_LIMIT = 2000
LONG_TEXT_LIMIT = 50000

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("voxcpm-web")


class ModelState:
    model = None
    error: Optional[str] = None
    lock = asyncio.Lock()


state = ModelState()


@dataclass
class GenerationJob:
    id: str
    status: str = "queued"
    current: int = 0
    total: int = 0
    progress: int = 0
    message: str = "等待 GPU"
    error: Optional[str] = None
    audio_url: Optional[str] = None
    filename: Optional[str] = None
    sample_rate: Optional[int] = None
    created_at: float = 0.0


jobs: dict[str, GenerationJob] = {}
job_tasks: set[asyncio.Task] = set()


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


@app.middleware("http")
async def disable_ui_cache(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


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
        "version": BUILD_VERSION,
        "long_form": True,
        "error": state.error,
    }


def _safe_control(control: str) -> str:
    return re.sub(r"[()（）]", "", control).strip()


def split_long_text(text: str, max_chars: int = 400) -> list[str]:
    """Split text on natural boundaries, with a hard upper bound per chunk."""
    text = re.sub(r"[ \t\f\v]+", " ", text).strip()
    if not text:
        return []

    units: list[str] = []
    for paragraph in re.split(r"\n+", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        units.extend(
            part.strip()
            for part in re.split(r"(?<=[。！？!?；;…])\s*", paragraph)
            if part.strip()
        )

    chunks: list[str] = []
    current = ""

    def append_oversized(value: str) -> None:
        nonlocal current
        while len(value) > max_chars:
            window = value[:max_chars]
            minimum = max(1, int(max_chars * 0.55))
            cut = max(
                window.rfind(mark, minimum)
                for mark in ("，", ",", "、", "：", ":", " ")
            )
            if cut < minimum:
                cut = max_chars
            else:
                cut += 1
            chunks.append(value[:cut].strip())
            value = value[cut:].strip()
        current = value

    for unit in units:
        candidate = f"{current}{unit}" if not current else f"{current} {unit}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current.strip())
            current = ""
        append_oversized(unit)

    if current:
        chunks.append(current.strip())
    return [chunk for chunk in chunks if chunk]


def _prune_jobs() -> None:
    cutoff = time.time() - 24 * 60 * 60
    stale = [
        job_id
        for job_id, job in jobs.items()
        if job.created_at < cutoff and job.status in {"completed", "failed"}
    ]
    for job_id in stale:
        jobs.pop(job_id, None)


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


def _generation_kwargs(
    text: str,
    *,
    mode: str,
    control: str,
    prompt_text: str,
    reference_path: Optional[Path],
    cfg_value: float,
    inference_timesteps: int,
    normalize: bool,
    denoise: bool,
    seed: Optional[int],
) -> dict:
    cleaned_control = _safe_control(control)
    final_text = f"({cleaned_control}){text}" if mode != "ultimate" and cleaned_control else text
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
    return kwargs


async def _run_long_job(
    job_id: str,
    chunks: list[str],
    settings: dict,
    reference_path: Optional[Path],
    pause_ms: int,
) -> None:
    job = jobs[job_id]
    job.total = len(chunks)
    output_path: Optional[Path] = None
    try:
        async with state.lock:
            job.status = "running"
            model = await asyncio.to_thread(load_model)
            sample_rate = int(model.tts_model.sample_rate)
            silence = np.zeros(int(sample_rate * pause_ms / 1000), dtype=np.float32)
            output_name = f"voxcpm-{uuid.uuid4().hex}.wav"
            output_path = OUTPUT_DIR / output_name

            # Write incrementally so very long documents do not keep hours of
            # generated audio in RAM before the final WAV can be downloaded.
            with sf.SoundFile(
                output_path, mode="w", samplerate=sample_rate, channels=1, subtype="PCM_16"
            ) as audio_file:
                for index, chunk in enumerate(chunks, start=1):
                    job.current = index
                    job.progress = int((index - 1) * 100 / len(chunks))
                    job.message = f"正在生成第 {index}／{len(chunks)} 段"
                    kwargs = _generation_kwargs(chunk, reference_path=reference_path, **settings)
                    wav = await asyncio.to_thread(model.generate, **kwargs)
                    audio_file.write(np.asarray(wav, dtype=np.float32).reshape(-1))
                    if pause_ms and index < len(chunks):
                        audio_file.write(silence)
                    job.progress = int(index * 100 / len(chunks))

        job.message = "正在完成音訊檔"
        job.status = "completed"
        job.progress = 100
        job.message = "長文語音已完成"
        job.audio_url = f"/api/audio/{output_name}"
        job.filename = output_name
        job.sample_rate = sample_rate
    except asyncio.CancelledError:
        if output_path is not None:
            output_path.unlink(missing_ok=True)
        job.status = "failed"
        job.message = "伺服器停止，工作已取消"
        job.error = "generation cancelled"
        raise
    except Exception as exc:
        logger.exception("Long-form generation failed")
        if output_path is not None:
            output_path.unlink(missing_ok=True)
        job.status = "failed"
        job.message = "長文生成失敗"
        job.error = str(exc)
    finally:
        if reference_path is not None:
            reference_path.unlink(missing_ok=True)


@app.post("/api/generate")
async def generate(
    text: Annotated[str, Form(min_length=1, max_length=LONG_TEXT_LIMIT)],
    mode: Annotated[str, Form()] = "design",
    control: Annotated[str, Form(max_length=500)] = "",
    prompt_text: Annotated[str, Form(max_length=2000)] = "",
    cfg_value: Annotated[float, Form(ge=1.0, le=3.0)] = 2.0,
    inference_timesteps: Annotated[int, Form(ge=1, le=50)] = 10,
    normalize: Annotated[bool, Form()] = False,
    denoise: Annotated[bool, Form()] = False,
    seed: Annotated[Optional[int], Form(ge=0, le=2147483647)] = None,
    long_form: Annotated[bool, Form()] = False,
    segment_chars: Annotated[int, Form(ge=100, le=800)] = 400,
    pause_ms: Annotated[int, Form(ge=0, le=2000)] = 250,
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
    if not long_form and len(text) > SHORT_TEXT_LIMIT:
        raise HTTPException(400, f"短文模式最多 {SHORT_TEXT_LIMIT} 字元，請開啟長文模式")

    reference_path: Optional[Path] = None
    handoff_reference = False
    try:
        if reference_audio is not None:
            reference_path = await _save_upload(reference_audio)

        settings = {
            "mode": mode,
            "control": control,
            "prompt_text": prompt_text,
            "cfg_value": cfg_value,
            "inference_timesteps": inference_timesteps,
            "normalize": normalize,
            "denoise": denoise,
            "seed": seed,
        }

        if long_form:
            chunks = split_long_text(text, segment_chars)
            if not chunks:
                raise HTTPException(400, "無法從文字建立有效段落")
            _prune_jobs()
            job_id = uuid.uuid4().hex
            jobs[job_id] = GenerationJob(
                id=job_id,
                total=len(chunks),
                created_at=time.time(),
                message=f"已分成 {len(chunks)} 段，等待 GPU",
            )
            task = asyncio.create_task(
                _run_long_job(job_id, chunks, settings, reference_path, pause_ms)
            )
            job_tasks.add(task)
            task.add_done_callback(job_tasks.discard)
            handoff_reference = True
            return {"job_id": job_id, "status": "queued", "total": len(chunks)}

        kwargs = _generation_kwargs(text, reference_path=reference_path, **settings)

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
        if reference_path is not None and not handoff_reference:
            reference_path.unlink(missing_ok=True)


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    if not re.fullmatch(r"[0-9a-f]{32}", job_id) or job_id not in jobs:
        raise HTTPException(404, "找不到此生成工作")
    return asdict(jobs[job_id])


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
