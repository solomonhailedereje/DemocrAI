from pathlib import Path

import numpy as np

from gr_rag.chunk import chunk_transcript, fmt_ts, split_text
from gr_rag.index import BM25, Hit, Retriever, tokenize
from gr_rag.rag import NO_INFO, RAG, Answer, validate
from gr_rag.scrape import parse_meeting_detail, parse_meeting_list, youtube_id, youtube_link

FIX = Path(__file__).parent / "fixtures"
BASE = "https://www.duebendorf.ch"


# ---------------------------------------------------------------- scraping

def test_parse_list():
    ms = parse_meeting_list((FIX / "list.html").read_text(), BASE)
    by_id = {m.id: m for m in ms}
    m = by_id["7667029"]
    assert (m.date, m.start, m.end) == ("2026-09-07", "19:00", "21:02")
    assert m.url == f"{BASE}/_rte/anlass/7667029"
    assert by_id["7558036"].cancelled
    assert by_id["7558042"].end is None


def test_parse_detail():
    m = parse_meeting_list((FIX / "list.html").read_text(), BASE)
    m = next(x for x in m if x.id == "7667029")
    parse_meeting_detail((FIX / "detail.html").read_text(), m, BASE)
    assert m.youtube_id == "23sjXudpV2w"
    assert [d.doc_type for d in m.documents] == ["TL", "PR"]
    assert m.protokolle[0].url == f"{BASE}/_doc/7271560"
    assert len(m.agenda) == 2
    assert m.agenda[1].number == "5" and "Einheitsgemeinde" in m.agenda[1].title
    assert m.agenda[1].documents[0].doc_type == "PO"
    assert all(d.url != f"{BASE}/_doc/7184359" for d in m.documents)  # agenda docs not duplicated


def test_youtube_ids():
    assert youtube_id("https://www.youtube.com/live/23sjXudpV2w") == "23sjXudpV2w"
    assert youtube_id("https://www.youtube.com/watch?v=abc123&t=5") == "abc123"
    assert youtube_id("https://youtu.be/xyz") == "xyz"
    assert youtube_link("abc", 125.7) == "https://www.youtube.com/watch?v=abc&t=125s"


# ---------------------------------------------------------------- chunking

def _segs(n, dur=10.0):
    return [{"start": i * dur, "end": (i + 1) * dur, "text": f"satz{i}"} for i in range(n)]


def test_chunk_transcript_covers_everything_with_overlap():
    segs = _segs(30)
    chunks = chunk_transcript(segs, window_s=75, overlap_s=15)
    text = " ".join(c["text"] for c in chunks)
    assert all(f"satz{i}" in text.split() for i in range(30))
    assert chunks[0]["start"] == 0 and chunks[-1]["end"] == 300
    for a, b in zip(chunks, chunks[1:]):
        assert b["start"] < a["end"]          # overlap
        assert b["start"] > a["start"]        # progress
    assert all(c["end"] - c["start"] <= 90 for c in chunks)


def test_chunk_single_and_long_segments():
    assert len(chunk_transcript(_segs(1), 75, 15)) == 1
    long = [{"start": 0, "end": 200, "text": "a"}, {"start": 200, "end": 400, "text": "b"}]
    assert len(chunk_transcript(long, 75, 15)) == 2


def test_split_text():
    t = ("Absatz eins. " * 30 + "\n\n" + "Absatz zwei. " * 30)
    parts = split_text(t, 200)
    assert all(len(p) <= 200 for p in parts) and len(parts) > 2


def test_fmt_ts():
    assert fmt_ts(3725) == "1:02:05"


# ---------------------------------------------------------------- retrieval

CHUNKS = [
    {"id": "a", "source_type": "transcript", "meeting_title": "3. Sitzung", "date": "2026-09-07",
     "text": "Thomas Maier von der GLP sagt, die Einheitsgemeinde mit der Sekundarschule bringe Synergien.",
     "start": 600, "end": 675, "label": "Video", "url": "u1"},
    {"id": "b", "source_type": "protokoll", "meeting_title": "3. Sitzung", "date": "2026-09-07",
     "text": "Der Gemeinderat schreibt das Postulat mit 25 zu 10 Stimmen ab.", "page": 4,
     "doc_title": "PR", "label": "Protokoll S. 4", "url": "u2"},
    {"id": "c", "source_type": "transcript", "meeting_title": "36. Sitzung", "date": "2026-03-31",
     "text": "Diskussion über das Budget der Badi und die Eintrittspreise.",
     "start": 0, "end": 70, "label": "Video", "url": "u3"},
]
VOCAB = ["einheitsgemeinde", "sekundarschule", "postulat", "budget", "badi", "stimmen"]


def fake_embed(texts):
    v = np.array([[t.lower().count(w) for w in VOCAB] for t in texts], dtype=np.float32) + 0.01
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def make_retriever():
    return Retriever(CHUNKS, fake_embed([c["text"] for c in CHUNKS]), embed_fn=fake_embed)


def test_tokenize_keeps_numbers():
    assert "03/2025" in tokenize("GR Geschäft Nr. 03/2025")
    assert "und" not in tokenize("Budget und Badi")


def test_bm25_ranks_keyword_match():
    bm = BM25([tokenize(c["text"]) for c in CHUNKS])
    assert int(np.argmax(bm.scores(tokenize("Badi Eintrittspreise")))) == 2


def test_retriever_hybrid_and_filters():
    r = make_retriever()
    assert r.search("Einheitsgemeinde Sekundarschule", top_k=1)[0].chunk["id"] == "a"
    hits = r.search("Einheitsgemeinde", source_types={"protokoll"})
    assert {h.chunk["source_type"] for h in hits} == {"protokoll"}
    hits = r.search("Budget", date_to="2026-04-01")
    assert [h.chunk["id"] for h in hits] == ["c"]


# ---------------------------------------------------------------- grounding

def _hits():
    return [Hit(c, 1.0, 0.9) for c in CHUNKS]


def test_validate_keeps_cited_drops_uncited_and_renumbers():
    raw = ("Thomas Maier (GLP) sah Synergien bei einer Einheitsgemeinde [1]. "
           "Das Postulat wurde mit 25 zu 10 Stimmen abgeschrieben [2]. "
           "Das ist sicher eine gute Entscheidung für die Stadt.")
    ans = validate(raw, _hits())
    assert ans.grounded
    assert "gute Entscheidung" not in ans.text
    assert len(ans.removed_sentences) == 1
    assert [s.n for s in ans.sources] == [1, 2]


def test_validate_renumbers_when_only_later_sources_cited():
    ans = validate("Es ging um die Badi [3].", _hits())
    assert ans.text == "Es ging um die Badi [1]."
    assert ans.sources[0].chunk["id"] == "c"


def test_validate_rejects_invented_citation_numbers():
    ans = validate("Der Stadtpräsident trat zurück [9].", _hits())
    assert not ans.grounded and ans.text == NO_INFO and ans.sources == []


def test_validate_passes_through_refusal():
    ans = validate(NO_INFO, _hits())
    assert not ans.grounded and ans.sources == []


def test_rag_refuses_without_calling_llm_when_nothing_relevant():
    called = []

    def chat(msgs):
        called.append(msgs)
        yield "x"

    rag = RAG(make_retriever(), chat_fn=chat)
    rag.min_score = 0.99
    ans = rag.ask("Wie ist das Wetter morgen?")
    assert ans.text == NO_INFO and not called


def test_rag_end_to_end_with_fake_llm():
    seen = {}

    def chat(msgs):
        seen["prompt"] = msgs[1]["content"]
        yield "Maier sah Synergien "
        yield "bei der Einheitsgemeinde [1]."

    rag = RAG(make_retriever(), chat_fn=chat)
    rag.min_score = 0.1
    items = list(rag.stream("Was sagte Maier zur Einheitsgemeinde?"))
    final = items[-1]
    assert isinstance(final, Answer) and final.grounded
    assert "[1] Transkript" in seen["prompt"] and "Video 0:10:00" in seen["prompt"]
    assert final.sources[0].chunk["url"] == "u1"
