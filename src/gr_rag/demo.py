"""Offline demo: fictional meetings + a keyword "embedder" + an extractive "LLM".

    gr-rag demo            # builds data-demo/ and serves http://localhost:8000
    login: demo@example.org / demo1234

Lets anyone try the full UI without Ollama, GPUs or real transcripts.
All names, parties and statements below are INVENTED for demonstration.
The extractive "LLM" only copies sentences from the excerpts (with [n]),
so the grounding and citation pipeline runs exactly as in production.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

import numpy as np

from .config import ROOT
from .index import STOPWORDS

DIM = 4096
DEMO_DIR = ROOT / "data-demo"


# --------------------------------------------------------------------------- fake models

def _stem(w: str) -> str:
    return re.sub(r"(en|er|es|e|n|s)$", "", w)


FILLER = STOPWORDS | set("""wurde wurden werden worden diskutiert gesagt sagt gab gibt gegeben welche welcher
welches haben hatte sein seine ihre wird soll sollte über unter beim zum zur vom heute morgen sowie dazu""".split())


def hash_embed(texts: list[str]) -> np.ndarray:
    """Hashed bag of stems + 5-letter prefixes (catches German compounds like Schulraum/Schulraumplanung).
    Lexical similarity only, but deterministic and offline."""
    out = np.zeros((len(texts), DIM), dtype=np.float32)
    for i, t in enumerate(texts):
        for w in re.findall(r"[a-zäöüß]{3,}", t.lower()):
            if w in FILLER:
                continue
            for key in {_stem(w), "p:" + w[:5]}:
                out[i, int(hashlib.md5(key.encode()).hexdigest(), 16) % DIM] += 1.0
    out += 1e-3
    return out / np.linalg.norm(out, axis=1, keepdims=True)


def extractive_chat(messages: list[dict], delay: float = 0.012):
    """Answer by quoting the first sentence of the most relevant excerpts, with citations."""
    user = messages[-1]["content"]
    question = user.split("FRAGE:", 1)[-1]
    q = set(_stem(w) for w in re.findall(r"[a-zäöüß]{4,}", question.lower()))
    blocks = re.findall(r"^\[(\d+)\][^\n]*\n(.+?)(?=\n\n\[\d+\]|\n\nFRAGE:|\Z)", user, flags=re.S | re.M)
    wants_votes = question.lstrip().startswith("Liste")   # only the outcomes task
    vote_re = re.compile(r"\d+ zu \d+|einstimmig|erledigt|genehmigt|angenommen|überwiesen", re.I)
    scored = []
    for n, text in blocks:
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text.strip()) if len(s.strip()) > 40]
        for s in sents:
            if not s.endswith((".", "!", "?")):      # skip headings / titles
                continue
            if wants_votes and not vote_re.search(s):
                continue
            overlap = len(q & set(_stem(w) for w in re.findall(r"[a-zäöüß]{4,}", s.lower())))
            scored.append((overlap + (5 if wants_votes else 0), -int(n), s, n))
    scored.sort(reverse=True)
    picked, seen = [], set()
    for ov, _, s, n in scored:
        if s in seen or (picked and ov == 0):
            continue
        picked.append(f"{s.rstrip('.')} [{n}].")
        seen.add(s)
        if len(picked) == 3:
            break
    answer = " ".join(picked) if picked else ("Dazu finde ich in den Transkripten und Protokollen der "
                                               "Gemeinderatssitzungen keine Angaben.")
    for tok in re.findall(r"\S+\s*", answer):
        time.sleep(delay)
        yield tok


# --------------------------------------------------------------------------- fictional content

PEOPLE = ["Gemeinderätin Anna Beispiel (Fraktion A)", "Gemeinderat Marco Muster (Fraktion B)",
          "Gemeinderätin Lea Probst (Fraktion C)", "Stadtrat Urs Vorlage"]

MEETINGS = [
    {"id": "9001", "title": "1. Demo-Sitzung des Gemeinderates", "date": "2026-09-07", "start": "19:00", "end": "21:05",
     "agenda": [
         ("1", "Mitteilungen", []),
         ("2", "Postulat «Schulraum für wachsende Quartiere» / Beantwortung", ["PO"]),
         ("3", "Kredit für sichere Velowege an der Seestrasse", ["BS"]),
         ("4", "Interpellation «Hitzeschutz auf Pausenplätzen» / Beantwortung", ["IP"]),
     ]},
    {"id": "9002", "title": "2. Demo-Sitzung des Gemeinderates", "date": "2026-10-05", "start": "19:00", "end": "22:10",
     "agenda": [
         ("1", "Mitteilungen", []),
         ("2", "Budget 2027 der Stadt", ["BS"]),
         ("3", "Motion «Digitale Verwaltung ohne Papierformulare»", ["MO"]),
         ("4", "Postulat «Schulraum für wachsende Quartiere» / Abschreibung", ["PO"]),
     ]},
]

TOPIC_TEXT = {
    "Mitteilungen": [
        "Ich begrüsse Sie zur heutigen Sitzung und stelle fest, dass der Rat beschlussfähig ist.",
        "Die nächste Sitzung findet wie geplant im Saal der Oberen Mühle statt.",
    ],
    "Schulraum": [
        "{p0} sagt, die Schülerzahlen im Quartier Nord würden bis 2030 um rund zwanzig Prozent steigen.",
        "Der Stadtrat schlägt vor, zuerst ein Provisorium mit sechs Klassenzimmern zu prüfen.",
        "{p1} kritisiert, ein Provisorium sei teurer als ein früh geplanter Neubau.",
        "{p2} beantragt, dass die Schulraumplanung jährlich im Gemeinderat vorgestellt wird.",
    ],
    "Velowege": [
        "{p3} erklärt, der Kredit von 1,8 Millionen Franken finanziere durchgehende Velostreifen an der Seestrasse.",
        "{p1} befürchtet, dass dadurch zwölf Parkplätze wegfallen.",
        "{p0} betont, die Seestrasse sei ein wichtiger Schulweg und brauche mehr Sicherheit.",
    ],
    "Hitzeschutz": [
        "{p2} fragt, wie viele Pausenplätze bis zum nächsten Sommer beschattet werden.",
        "{p3} antwortet, dass auf drei Pausenplätzen Bäume gepflanzt und Sonnensegel montiert werden.",
    ],
    "Budget": [
        "{p3} stellt das Budget 2027 mit einem Aufwandüberschuss von 2,4 Millionen Franken vor.",
        "{p1} beantragt, den Steuerfuss unverändert zu lassen.",
        "{p0} verlangt mehr Mittel für die Schulsozialarbeit.",
        "Die Finanzkommission empfiehlt, dem Budget zuzustimmen.",
    ],
    "Digitale": [
        "{p2} fordert, dass alle Formulare der Verwaltung bis 2028 online ausgefüllt werden können.",
        "{p3} weist darauf hin, dass dafür zusätzliche Informatikstellen nötig wären.",
        "{p1} unterstützt die Motion, möchte aber Open-Source-Lösungen bevorzugen.",
    ],
}

OUTCOMES = {
    ("9001", "2"): "Der Gemeinderat nimmt die Beantwortung des Postulats mit 28 zu 6 Stimmen zur Kenntnis.",
    ("9001", "3"): "Der Kredit für die Velowege an der Seestrasse wird mit 22 zu 12 Stimmen angenommen.",
    ("9001", "4"): "Die Interpellation ist erledigt; eine Diskussion wird nicht verlangt.",
    ("9002", "2"): "Das Budget 2027 wird mit 25 zu 9 Stimmen genehmigt, der Steuerfuss bleibt unverändert.",
    ("9002", "3"): "Die Motion wird mit 19 zu 15 Stimmen an den Stadtrat überwiesen.",
    ("9002", "4"): "Das Postulat wird einstimmig als erledigt abgeschrieben.",
}

NUM_WORDS = {"1": "eins", "2": "zwei", "3": "drei", "4": "vier"}


def _topic(title: str) -> str:
    for k in TOPIC_TEXT:
        if k.lower() in title.lower():
            return k
    return "Mitteilungen"


def _fill(s: str) -> str:
    return s.format(**{f"p{i}": p for i, p in enumerate(PEOPLE)})


def build_demo(data: Path = DEMO_DIR) -> Path:
    os.environ["GR_RAG_DATA"] = str(data)
    from .chunk import build_chunks
    from .config import paths
    from .index import Retriever
    from .store import Store
    from .summarize import summarize_meeting

    p = paths()
    meetings, doc_counter = [], 7000
    for m in MEETINGS:
        agenda, docs_meeting = [], []
        segs, t = [], 0.0
        for num, title, doc_types in m["agenda"]:
            docs = []
            for dt in doc_types:
                doc_counter += 1
                d = {"title": f"{m['date'].replace('-', '')}-{dt}-{title.split(' / ')[0][:50]}",
                     "url": f"https://example.org/_doc/{doc_counter}", "doc_type": dt}
                docs.append(d)
                body = [_fill(s) for s in TOPIC_TEXT[_topic(title)]]
                (p.docs / f"{doc_counter}.json").write_text(json.dumps({
                    "doc_id": str(doc_counter), "title": d["title"], "url": d["url"], "doc_type": dt,
                    "meetings": [m["id"]], "pages": [
                        {"page": 1, "text": f"{title}\n\nAusgangslage. " + " ".join(body[:2])},
                        {"page": 2, "text": "Erwägungen. " + " ".join(body[2:]) + " Der Stadtrat beantragt Zustimmung."},
                    ]}, ensure_ascii=False))
            agenda.append({"number": num, "title": title, "geschaeft": f"2026-{int(num) + 10}", "documents": docs})
            # transcript: announcement + statements, ~25 s per sentence
            segs.append({"start": t, "end": t + 8, "text": f"Wir kommen zu Traktandum {NUM_WORDS[num]}, {title.split(' / ')[0]}."})
            t += 10
            for s in TOPIC_TEXT[_topic(title)] * 2:
                segs.append({"start": t, "end": t + 22, "text": _fill(s)})
                t += 25
        (p.transcripts / f"{m['id']}.json").write_text(json.dumps(
            {"meeting_id": m["id"], "model": "demo", "backend": "demo", "complete": True, "segments": segs}, ensure_ascii=False))

        doc_counter += 1
        pr = {"title": f"{m['date'].replace('-', '')}-PR-Protokoll {m['title']}", "url": f"https://example.org/_doc/{doc_counter}", "doc_type": "PR"}
        docs_meeting.append(pr)
        pr_pages = []
        for num, title, _ in m["agenda"]:
            body = " ".join(_fill(s) for s in TOPIC_TEXT[_topic(title)][:2])
            outcome = OUTCOMES.get((m["id"], num), "")
            pr_pages.append({"page": int(num), "text": f"Traktandum {num}: {title}\n\n{body} {outcome}"})
        (p.docs / f"{doc_counter}.json").write_text(json.dumps({
            "doc_id": str(doc_counter), "title": pr["title"], "url": pr["url"], "doc_type": "PR",
            "meetings": [m["id"]], "pages": pr_pages}, ensure_ascii=False))

        meetings.append({**{k: m[k] for k in ("id", "title", "date", "start", "end")},
                         "url": "https://example.org/sitzung/" + m["id"], "cancelled": False,
                         "youtube_url": None, "youtube_id": None, "documents": docs_meeting, "agenda": agenda})
    meetings.append({"id": "9003", "title": "3. Demo-Sitzung des Gemeinderates", "url": "https://example.org/sitzung/9003",
                     "date": "2027-02-01", "start": "19:00", "end": None, "cancelled": False, "youtube_url": None,
                     "youtube_id": None, "documents": [], "agenda": []})
    p.meetings.write_text(json.dumps(meetings, ensure_ascii=False, indent=1), encoding="utf-8")

    chunks = build_chunks()
    np.save(p.index / "embeddings.npy", hash_embed([c["text"] for c in chunks]))
    with open(p.index / "chunks.jsonl", "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    retriever = Retriever(embed_fn=hash_embed)
    fast = lambda msgs: extractive_chat(msgs, delay=0)  # noqa: E731
    for m in meetings[:2]:
        s = summarize_meeting(retriever, m, chat_fn=fast)
        (p.summaries / f"{m['id']}.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")

    store = Store(p.db)
    if not any(u["email"] == "demo@example.org" for u in store.list_users()):
        store.add_user("demo@example.org", "Demo Nutzerin", "demo1234")
    print(f"Demo data in {data}  ({len(chunks)} chunks).  Login: demo@example.org / demo1234")
    return data


def demo_app():
    os.environ["GR_RAG_DATA"] = str(DEMO_DIR)
    if not (DEMO_DIR / "index" / "chunks.jsonl").exists():
        build_demo()
    from .api import create_app
    from .index import Retriever
    from .rag import RAG

    def factory():
        rag = RAG(Retriever(embed_fn=hash_embed), chat_fn=extractive_chat)
        rag.min_score = 0.12
        return rag

    return create_app(rag_factory=factory)
