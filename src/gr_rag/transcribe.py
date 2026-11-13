"""Transcribe meeting audio with the Swiss German Whisper fine-tune.

Output per meeting: data/transcripts/<id>.json
  {"meeting_id", "model", "backend", "complete": bool,
   "segments": [{"start": s, "end": s, "text": "..."}]}

Timestamps are what make citations possible: every answer links to the
exact second in the YouTube recording.

Two backends:
  faster-whisper  CTranslate2, int8 on CPU. Best choice for an Intel Mac,
                  also very fast on a CUDA GPU (Colab / ScienceCluster).
  transformers    Plain Hugging Face pipeline. Simpler, needs torch.

The faster-whisper backend is *resumable*: progress is flushed to disk
every few minutes, and a restart continues where it stopped. That matters
when a 4-hour meeting takes most of a night on a laptop CPU.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from .config import ROOT, load_config, paths

FLUSH_EVERY_S = 120


# --------------------------------------------------------------------------- model conversion

def convert_model() -> Path:
    """Convert the HF checkpoint to CTranslate2 format (one-off, ~2 GB download)."""
    import ctranslate2
    from huggingface_hub import snapshot_download

    cfg = load_config()["transcribe"]
    out = ROOT / cfg["ct2_dir"]
    if (out / "model.bin").exists():
        print(f"CT2 model already at {out}")
        return out

    # snapshot_download also works offline (HF_HUB_OFFLINE=1) once the files are cached,
    # which matters on cluster compute nodes without internet. Prefetch with
    # `gr-rag prefetch-model` on a login node.
    local = Path(snapshot_download(cfg["model_id"]))
    copy = [f for f in ("tokenizer.json", "preprocessor_config.json") if (local / f).exists()]
    print(f"Converting {cfg['model_id']} -> {out} (copying {copy})")
    ctranslate2.converters.TransformersConverter(str(local), copy_files=copy).convert(
        str(out), quantization="float16", force=True
    )
    # faster-whisper needs tokenizer.json + preprocessor_config.json (128 mel bins for v3).
    # If the fine-tune repo lacks them, take them from the base model (same vocabulary).
    missing = [f for f in ("tokenizer.json", "preprocessor_config.json") if not (out / f).exists()]
    if missing:
        base = Path(snapshot_download(BASE_MODEL, allow_patterns=missing))
        for fname in missing:
            shutil.copy(base / fname, out / fname)
            print(f"  copied {fname} from {BASE_MODEL}")
    return out


BASE_MODEL = "openai/whisper-large-v3-turbo"


def prefetch_model() -> None:
    """Download model files into the HF cache (run where there is internet)."""
    from huggingface_hub import snapshot_download

    model_id = load_config()["transcribe"]["model_id"]
    print("  ", snapshot_download(model_id))
    print("  ", snapshot_download(BASE_MODEL, allow_patterns=["tokenizer.json", "preprocessor_config.json"]))


# --------------------------------------------------------------------------- backends

def _resolve_device(cfg: dict) -> tuple[str, str]:
    device = cfg["device"]
    if device == "auto":
        try:
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    compute = cfg["compute_type"]
    if compute == "auto":
        compute = "float16" if device == "cuda" else "int8"
    return device, compute


def _save(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _transcribe_faster_whisper(audio: Path, out: Path, meeting_id: str, cfg: dict) -> None:
    from faster_whisper import WhisperModel

    model_dir = ROOT / cfg["ct2_dir"]
    if not (model_dir / "model.bin").exists():
        raise SystemExit("CTranslate2 model missing - run `gr-rag convert-model` first.")
    device, compute = _resolve_device(cfg)

    payload = {"meeting_id": meeting_id, "model": cfg["model_id"], "backend": "faster-whisper",
               "complete": False, "segments": []}
    if out.exists():
        payload = json.loads(out.read_text(encoding="utf-8"))
        if payload.get("complete"):
            return
    resume_at = payload["segments"][-1]["end"] if payload["segments"] else 0.0
    if resume_at:
        print(f"    resuming at {resume_at/60:.1f} min")

    model = WhisperModel(str(model_dir), device=device, compute_type=compute)
    segments, info = model.transcribe(
        str(audio),
        language=cfg["language"],
        beam_size=cfg["beam_size"],
        vad_filter=cfg["vad_filter"],
        condition_on_previous_text=False,   # avoids repetition loops on long recordings
        clip_timestamps=[resume_at] if resume_at else "0",
    )
    total = info.duration or 1
    t0 = last_flush = time.time()
    for seg in segments:
        text = seg.text.strip()
        if text:
            payload["segments"].append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": text})
        if time.time() - last_flush > FLUSH_EVERY_S:
            _save(out, payload)
            last_flush = time.time()
            done = seg.end / total
            speed = (seg.end - resume_at) / max(time.time() - t0, 1)
            eta = (total - seg.end) / max(speed, 1e-6) / 60
            print(f"    {done:5.1%}  speed {speed:4.1f}x realtime  ETA {eta:5.0f} min")
    payload["complete"] = True
    _save(out, payload)


def _transcribe_transformers(audio: Path, out: Path, meeting_id: str, cfg: dict) -> None:
    import torch
    from transformers import pipeline

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device != "cpu" else torch.float32
    asr = pipeline("automatic-speech-recognition", model=cfg["model_id"], torch_dtype=dtype,
                   device=device, chunk_length_s=30, batch_size=8 if device != "cpu" else 1)
    result = asr(str(audio), return_timestamps=True,
                 generate_kwargs={"language": "german", "task": "transcribe"})
    segs = []
    for c in result.get("chunks", []):
        start, end = c["timestamp"]
        if c["text"].strip():
            segs.append({"start": round(start or 0, 2), "end": round(end or start or 0, 2),
                         "text": c["text"].strip()})
    _save(out, {"meeting_id": meeting_id, "model": cfg["model_id"], "backend": "transformers",
                "complete": True, "segments": segs})


# --------------------------------------------------------------------------- driver

def transcribe_all(meeting_ids: list[str] | None = None) -> None:
    cfg = load_config()["transcribe"]
    p = paths()
    fn = _transcribe_faster_whisper if cfg["backend"] == "faster-whisper" else _transcribe_transformers
    from .download import AUDIO_EXTS
    audio_files = sorted(f for f in p.audio.iterdir() if f.suffix in AUDIO_EXTS)
    if not audio_files:
        print("No audio in data/audio - run `gr-rag download-audio` first.")
    for audio in audio_files:
        mid = audio.stem
        if meeting_ids and mid not in meeting_ids:
            continue
        out = p.transcripts / f"{mid}.json"
        if out.exists() and json.loads(out.read_text(encoding="utf-8")).get("complete"):
            print(f"  skip {mid} (done)")
            continue
        print(f"  transcribing {mid} with {cfg['backend']}")
        fn(audio, out, mid, cfg)
