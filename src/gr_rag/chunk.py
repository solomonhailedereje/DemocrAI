"""Turn transcripts and Protokoll pages into citable chunks.

Every chunk carries enough metadata to show the user exactly where it came
from: meeting, date, and either a YouTube timestamp or a PDF page.
"""
from __future__ import annotations

import json
import re

from .config import load_config, paths
from .scrape import load_meetings, youtube_link


def fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def chunk_transcript(segments: list[dict], window_s: float, overlap_s: float) -> list[dict]:
    """Group consecutive segments into ~window_s windows with overlap_s overlap."""
    chunks: list[dict] = []
    i, n = 0, len(segments)
    while i < n:
        start = segments[i]["start"]
        j = i
        while j < n and segments[j]["end"] - start < window_s:
            j += 1
        j = min(j, n - 1)
        group = segments[i : j + 1]
        chunks.append({
            "start": group[0]["start"],
            "end": group[-1]["end"],
            "text": " ".join(s["text"] for s in group),
        })
        if j == n - 1:
            break
        # next chunk starts overlap_s before this one ended, but always advances
        next_start = group[-1]["end"] - overlap_s
        k = i + 1
        while k <= j and segments[k]["start"] < next_start:
            k += 1
        i = max(k, i + 1)
    return chunks


def split_text(text: str, max_chars: int) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n(?=[A-ZÄÖÜ0-9])", text) if p.strip()]
    out, buf = [], ""
    for p in paras:
        if len(buf) + len(p) + 1 <= max_chars:
            buf = f"{buf}\n{p}" if buf else p
        else:
            if buf:
                out.append(buf)
            while len(p) > max_chars:  # very long paragraph: cut at sentence end
                cut = p.rfind(". ", 0, max_chars)
                cut = cut + 1 if cut > max_chars // 2 else max_chars
                out.append(p[:cut].strip())
                p = p[cut:].strip()
            buf = p
    if buf:
        out.append(buf)
    return out


def build_chunks() -> list[dict]:
    cfg = load_config()["chunking"]
    p = paths()
    meetings = {m["id"]: m for m in load_meetings()}
    chunks: list[dict] = []

    for tfile in sorted(p.transcripts.glob("*.json")):
        t = json.loads(tfile.read_text(encoding="utf-8"))
        m = meetings.get(t["meeting_id"], {})
        if not t.get("complete"):
            print(f"  note: transcript {tfile.stem} is incomplete, indexing what exists")
        for c in chunk_transcript(t["segments"], cfg["transcript_window_s"], cfg["transcript_overlap_s"]):
            vid = m.get("youtube_id")
            chunks.append({
                "id": f"T-{t['meeting_id']}-{int(c['start'])}",
                "source_type": "transcript",
                "meeting_id": t["meeting_id"],
                "meeting_title": m.get("title", ""),
                "date": m.get("date"),
                "text": c["text"],
                "start": c["start"],
                "end": c["end"],
                "label": f"Video {fmt_ts(c['start'])}–{fmt_ts(c['end'])}",
                "url": youtube_link(vid, c["start"]) if vid else m.get("url"),
            })

    for dfile in sorted(p.docs.glob("*.json")):
        chunks.extend(doc_chunks(json.loads(dfile.read_text(encoding="utf-8")), meetings, cfg["protokoll_max_chars"]))
    return chunks


def doc_chunks(doc: dict, meetings: dict, max_chars: int) -> list[dict]:
    """Chunks for one PDF. Protokolle (doc_type PR) are their own source type;
    everything else (Postulate, Stadtrat decisions, ...) is 'dokument'."""
    mids = [mid for mid in doc["meetings"] if mid in meetings] or doc["meetings"]
    # attribute a document to its earliest meeting (where it was first discussed)
    mids = sorted(mids, key=lambda i: meetings.get(i, {}).get("date") or "")
    m = meetings.get(mids[0], {}) if mids else {}
    is_pr = doc["doc_type"] == "PR"
    out = []
    for page in doc["pages"]:
        for k, piece in enumerate(split_text(page["text"], max_chars)):
            out.append({
                "id": f"D-{doc['doc_id']}-{page['page']}-{k}",
                "source_type": "protokoll" if is_pr else "dokument",
                "meeting_id": mids[0] if mids else None,
                "meeting_ids": mids,
                "meeting_title": m.get("title", ""),
                "date": m.get("date"),
                "text": piece,
                "doc_id": doc["doc_id"],
                "doc_title": doc["title"],
                "doc_type": doc["doc_type"],
                "page": page["page"],
                "label": f"{'Protokoll' if is_pr else 'Dokument'} S. {page['page']}",
                "url": f"{doc['url']}#page={page['page']}",
            })
    return out
