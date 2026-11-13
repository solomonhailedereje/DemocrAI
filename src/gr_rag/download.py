"""Download meeting audio (from YouTube) and meeting documents (PDF), extract PDF text."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

from .config import load_config, paths
from .scrape import load_meetings


def download_audio(meeting_ids: list[str] | None = None) -> None:
    """Fetch the audio track only, in its native compressed format (m4a/webm,
    ~30 MB per hour). Whisper decodes it directly, so no conversion is needed."""
    import yt_dlp  # imported lazily: optional dependency

    out_dir = paths().audio
    for m in load_meetings():
        if meeting_ids and m["id"] not in meeting_ids:
            continue
        if not m.get("youtube_id"):
            continue
        if audio_file(m["id"]):
            print(f"  skip {m['id']} (audio exists)")
            continue
        print(f"  downloading {m['date']} {m['title']} ({m['youtube_id']})")
        opts = {
            "format": "bestaudio[ext=m4a]/bestaudio",
            "outtmpl": str(out_dir / f"{m['id']}.%(ext)s"),
            "quiet": True,
            "noprogress": False,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                try:
                    ydl.download([f"https://www.youtube.com/watch?v={m['youtube_id']}"])
                except Exception as e:
                    print(f"  ! skipped {m['youtube_id']}: {str(e).splitlines()[0][:150]}")
            except Exception as e:
                print(f"  ! skipped {m['youtube_id']}: {str(e).splitlines()[0][:150]}")
AUDIO_EXTS = (".m4a", ".webm", ".opus", ".mp3", ".wav", ".ogg")


def audio_file(meeting_id: str) -> Path | None:
    for ext in AUDIO_EXTS:
        f = paths().audio / f"{meeting_id}{ext}"
        if f.exists():
            return f
    return None


def _safe(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name)[:120]


def doc_id(url: str) -> str:
    return url.rstrip("/").split("/")[-1].split("#")[0]


def meeting_documents(m: dict) -> list[dict]:
    """All documents of a meeting: meeting-level + those attached to agenda items."""
    docs = {d["url"]: {**d, "agenda": None} for d in m.get("documents", [])}
    for item in m.get("agenda", []):
        for d in item.get("documents", []):
            docs.setdefault(d["url"], {**d, "agenda": item["number"]})
    return list(docs.values())


def download_documents(only_types: set[str] | None = None) -> None:
    """Download PDFs and extract text per page -> data/docs/<doc_id>.json.

    A document (e.g. a Postulat) is often listed in several meetings; it is
    stored once, with the list of meetings it belongs to.
    """
    p = paths()
    s = requests.Session()
    s.headers["User-Agent"] = load_config()["scrape"]["user_agent"]
    delay = load_config()["scrape"]["delay_seconds"]

    for m in load_meetings():
        for d in meeting_documents(m):
            if only_types and d["doc_type"] not in only_types:
                continue
            did = doc_id(d["url"])
            out = p.docs / f"{did}.json"
            if out.exists():
                rec = json.loads(out.read_text(encoding="utf-8"))
                if m["id"] not in rec["meetings"]:
                    rec["meetings"].append(m["id"])
                    out.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
                continue
            pdf_path = p.pdfs / f"{did}.pdf"
            if not pdf_path.exists():
                r = s.get(d["url"], timeout=60)
                r.raise_for_status()
                pdf_path.write_bytes(r.content)
                time.sleep(delay)
            try:
                pages = [{"page": n, "text": t} for n, t in extract_pdf_pages(pdf_path)]
            except Exception as e:  # damaged / scanned PDF
                print(f"  ! could not read {d['title']}: {e}")
                pages = []
            rec = {"doc_id": did, "title": d["title"], "url": d["url"], "doc_type": d["doc_type"],
                   "meetings": [m["id"]], "pages": pages}
            out.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  {m['date']} {d['title'][:70]}: {len(pages)} pages")


def load_doc(did: str) -> dict | None:
    f = paths().docs / f"{did}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def extract_pdf_pages(pdf_path: Path) -> list[tuple[int, str]]:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    out = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"-\n(?=[a-zäöü])", "", text)  # re-join hyphenated words
        if text:
            out.append((i, text))
    return out
