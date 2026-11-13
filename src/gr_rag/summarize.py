"""Pre-computed, cited meeting overviews for the Sitzung page.

Per meeting -> data/summaries/<meeting_id>.json
  chapters : agenda items aligned to video timestamps
  items    : per agenda item, a short summary from the video transcript and one
             from the Protokoll, each with its own sources
  outcomes : decisions / votes listed in the Protokoll, with sources
Per document -> data/summaries/docs/<doc_id>.json (generated on demand, cached)

Every generated text goes through rag.validate(): sentences without a valid
citation are dropped, exactly like chat answers.

Chapters need no LLM: the council president usually announces
"Traktandum 5 ..."; we detect those announcements and combine them with
embedding similarity in a monotonic alignment (dynamic programming), so
agenda order is always respected.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

import numpy as np

from .config import load_config, paths
from .index import Hit, Retriever
from .rag import NO_INFO, Answer, generate
from .scrape import load_meetings

NUM_WORDS = {w: i for i, w in enumerate(
    "null eins zwei drei vier fünf sechs sieben acht neun zehn elf zwölf dreizehn vierzehn "
    "fünfzehn sechzehn siebzehn achtzehn neunzehn zwanzig".split())}
NUM_WORDS["ein"] = NUM_WORDS["erste"] = 1
ANNOUNCE_RE = re.compile(r"traktand\w*\s*(?:nr\.?|nummer)?\s*(\d{1,2}|[a-zäöü]+)", re.IGNORECASE)
OUTCOME_RE = re.compile(r"abstimm|stimmen|beschlie|beschluss(?!fähig)|angenommen|abgelehnt|einstimmig|"
                        r"genehmigt|abgeschrieben|überwiesen|zustimm", re.IGNORECASE)


# --------------------------------------------------------------------------- serialisation

def cited(ans: Answer) -> dict | None:
    if not ans.grounded:
        return None
    return {"text": ans.text, "sources": [{"n": s.n, "chunk": s.chunk} for s in ans.sources]}


# --------------------------------------------------------------------------- chapters

def announced_numbers(text: str) -> set[int]:
    out = set()
    for tok in ANNOUNCE_RE.findall(text):
        tok = tok.lower()
        if tok.isdigit():
            out.add(int(tok))
        elif tok in NUM_WORDS:
            out.add(NUM_WORDS[tok])
    return out


def align_chapters(agenda: list[dict], windows: list[dict], sim: np.ndarray,
                   announce_bonus: float = 1.0) -> list[dict]:
    """Assign each agenda item a start window, strictly increasing in agenda order.

    agenda : [{number, title}], windows: [{start, end, text}] sorted by time,
    sim    : (n_items, n_windows) similarity of item title to window text.
    Maximises total score = similarity + bonus where "Traktandum <n>" is announced.
    """
    n, m = len(agenda), len(windows)
    if n == 0 or m == 0:
        return []
    if m < n:  # too little transcript to separate items
        return []
    score = sim.astype(np.float64).copy()
    announced = [announced_numbers(w["text"]) for w in windows]
    for i, item in enumerate(agenda):
        num = int(item["number"]) if str(item["number"]).isdigit() else None
        for j in range(m):
            if num is not None and num in announced[j]:
                score[i, j] += announce_bonus

    # dp[i, j] = best total for items 0..i with item i starting at window j
    dp = np.full((n, m), -np.inf)
    back = np.zeros((n, m), dtype=int)
    dp[0] = score[0]
    for i in range(1, n):
        best, arg = -np.inf, -1
        for j in range(m):
            if j >= 1 and dp[i - 1, j - 1] > best:      # running prefix max of previous row
                best, arg = dp[i - 1, j - 1], j - 1
            if arg >= 0:
                dp[i, j] = best + score[i, j]
                back[i, j] = arg
    j = int(np.argmax(dp[n - 1]))
    starts = [0] * n
    for i in range(n - 1, -1, -1):
        starts[i] = j
        j = back[i, j]

    chapters = []
    for i, item in enumerate(agenda):
        s = starts[i]
        num = int(item["number"]) if str(item["number"]).isdigit() else None
        chapters.append({
            "number": item["number"],
            "title": item["title"],
            "start": 0.0 if i == 0 else windows[s]["start"],
            "end": windows[starts[i + 1]]["start"] if i + 1 < n else windows[-1]["end"],
            "confidence": "announced" if num is not None and num in announced[s] else "estimated",
        })
    return chapters


def meeting_chapters(retriever: Retriever, meeting: dict) -> list[dict]:
    idx = [i for i, c in enumerate(retriever.chunks)
           if c["source_type"] == "transcript" and c["meeting_id"] == meeting["id"]]
    idx.sort(key=lambda i: retriever.chunks[i]["start"])
    agenda = meeting.get("agenda") or []
    if not idx or not agenda:
        return []
    windows = [retriever.chunks[i] for i in idx]
    q = retriever.embed_fn([f"Traktandum {a['number']}: {a['title']}" for a in agenda])
    sim = q @ retriever.vecs[idx].T
    return align_chapters(agenda, windows, sim)


# --------------------------------------------------------------------------- summaries

def summarize_meeting(retriever: Retriever, meeting: dict, chat_fn=None) -> dict:
    mid = {meeting["id"]}
    chapters = meeting_chapters(retriever, meeting)
    by_num = {c["number"]: c for c in chapters}
    items = []
    for a in meeting.get("agenda") or []:
        ch = by_num.get(a["number"])
        topic = f"Traktandum {a['number']}: {a['title']}"
        video = None
        if ch:
            hits = retriever.search(a["title"], top_k=5, meeting_ids=mid, source_types={"transcript"},
                                    time_range=(ch["start"], ch["end"]))
            video = cited(generate(
                f"Fasse in 2–4 Sätzen zusammen, was in der Sitzung zu «{topic}» gesagt wurde: "
                "Positionen, Argumente, wer sich äusserte (nur wenn genannt). Mit Quellen [n].",
                hits, chat_fn))
        hits = retriever.search(a["title"], top_k=4, meeting_ids=mid, source_types={"protokoll"})
        proto = cited(generate(
            f"Fasse in 2–3 Sätzen zusammen, was das Protokoll zu «{topic}» festhält, "
            "inklusive Beschluss und Stimmenverhältnis, falls genannt. Mit Quellen [n].",
            hits, chat_fn))
        items.append({"number": a["number"], "title": a["title"], "video": video, "protokoll": proto})
        print(f"    Traktandum {a['number']}: video={'✓' if video else '–'} protokoll={'✓' if proto else '–'}")

    # outcomes: Protokoll passages that mention votes/decisions, in batches
    proto_chunks = [c for c in retriever.chunks
                    if c["source_type"] == "protokoll" and meeting["id"] in (c.get("meeting_ids") or [])]
    relevant = [c for c in proto_chunks if OUTCOME_RE.search(c["text"])]
    outcomes = []
    for k in range(0, len(relevant), 5):
        batch = [Hit(c, 1.0, 1.0) for c in relevant[k:k + 5]]
        block = cited(generate(
            "Liste jeden Beschluss bzw. jede Abstimmung aus den Auszügen auf einer eigenen Zeile: "
            "Geschäft – Ergebnis (Stimmenverhältnis, falls angegeben) [n]. Nur ausdrücklich Genanntes.",
            batch, chat_fn))
        if block:
            outcomes.append(block)

    return {"meeting_id": meeting["id"], "generated_at": datetime.now().isoformat(timespec="seconds"),
            "model": load_config()["llm"]["model"], "chapters": chapters, "items": items, "outcomes": outcomes}


def summarize_document(retriever: Retriever, did: str, chat_fn=None, max_batches: int = 3) -> dict:
    chunks = [c for c in retriever.chunks if c.get("doc_id") == did]
    chunks.sort(key=lambda c: (c["page"], c["id"]))
    blocks = []
    for k in range(0, min(len(chunks), 6 * max_batches), 6):
        batch = [Hit(c, 1.0, 1.0) for c in chunks[k:k + 6]]
        block = cited(generate(
            "Fasse die wichtigsten Punkte dieser Seiten in 2–4 Sätzen zusammen: Worum geht es, "
            "was wird beantragt oder entschieden, welche Zahlen/Termine sind wichtig. Mit Quellen [n].",
            batch, chat_fn))
        if block:
            blocks.append(block)
    pages = sorted({c["page"] for c in chunks})
    covered = sorted({c["page"] for c in chunks[: 6 * max_batches]})
    return {"doc_id": did, "blocks": blocks, "pages_total": len(pages), "pages_covered": len(covered),
            "generated_at": datetime.now().isoformat(timespec="seconds")}


# --------------------------------------------------------------------------- storage

def load_summary(meeting_id: str) -> dict | None:
    f = paths().summaries / f"{meeting_id}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def doc_summary(retriever: Retriever, did: str, chat_fn=None, refresh: bool = False) -> dict:
    f = paths().summaries / "docs" / f"{did}.json"
    if f.exists() and not refresh:
        return json.loads(f.read_text(encoding="utf-8"))
    out = summarize_document(retriever, did, chat_fn)
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def summarize_all(meeting_ids: list[str] | None = None, refresh: bool = False) -> None:
    retriever = Retriever()
    for m in load_meetings():
        if m.get("cancelled") or (meeting_ids and m["id"] not in meeting_ids):
            continue
        f = paths().summaries / f"{m['id']}.json"
        if f.exists() and not refresh:
            continue
        print(f"  {m['date']} {m['title']}")
        out = summarize_meeting(retriever, m)
        f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


__all__ = ["align_chapters", "summarize_meeting", "summarize_document", "load_summary", "doc_summary",
           "summarize_all", "NO_INFO"]
