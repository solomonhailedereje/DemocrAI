"""API, auth, projects and chapter-alignment tests (fictional data, fake LLM)."""
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from gr_rag.chunk import doc_chunks
from gr_rag.rag import RAG
from gr_rag.store import Store, check_password, hash_password
from gr_rag.summarize import align_chapters, announced_numbers

from test_pipeline import make_retriever

MEETING = {
    "id": "100", "title": "Demo-Sitzung", "url": "https://example.org/100", "date": "2026-09-07",
    "start": "19:00", "end": "21:00", "cancelled": False, "youtube_url": None, "youtube_id": "demoVideo01",
    "documents": [{"title": "20260907-PR-Protokoll Demo", "url": "https://example.org/_doc/900", "doc_type": "PR"}],
    "agenda": [
        {"number": "1", "title": "Mitteilungen", "geschaeft": "", "documents": []},
        {"number": "2", "title": "Postulat Einheitsgemeinde / Beantwortung", "geschaeft": "2025-13",
         "documents": [{"title": "20250203-PO-Postulat Demo", "url": "https://example.org/_doc/901", "doc_type": "PO"}]},
    ],
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GR_RAG_DATA", str(tmp_path))
    (tmp_path / "meetings.json").write_text(json.dumps([MEETING]))
    (tmp_path / "transcripts").mkdir()
    (tmp_path / "transcripts" / "100.json").write_text(json.dumps({
        "meeting_id": "100", "complete": True,
        "segments": [{"start": 0, "end": 5, "text": "Ich eröffne die Sitzung."}]}))

    def chat(msgs):
        yield "Es wurden Synergien genannt [1]. "
        yield "Meine Meinung dazu ist positiv."

    rag = RAG(make_retriever(), chat_fn=chat)
    rag.min_score = 0.05
    from gr_rag.api import create_app
    store = Store(tmp_path / "app.db")
    store.add_user("anna@example.org", "Anna", "geheim123")
    store.add_user("ben@example.org", "Ben", "geheim456")
    app = create_app(store=store, rag_factory=lambda: rag)
    return TestClient(app)


def login(c, email="anna@example.org", pw="geheim123"):
    r = c.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return r


def test_password_hashing():
    h = hash_password("abcdefgh")
    assert check_password("abcdefgh", h) and not check_password("abcdefgX", h)


def test_auth_required_and_login(client):
    assert client.get("/api/meetings").status_code == 401
    assert client.post("/api/auth/login", json={"email": "anna@example.org", "password": "x"}).status_code == 401
    login(client)
    assert client.get("/api/auth/me").json()["name"] == "Anna"
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_meetings(client):
    login(client)
    ms = client.get("/api/meetings").json()
    assert ms[0]["id"] == "100" and ms[0]["has_transcript"] and ms[0]["has_protokoll"]
    m = client.get("/api/meetings/100").json()
    assert {d["doc_id"] for d in m["documents"]} == {"900", "901"}
    assert m["agenda"][1]["documents"][0]["doc_id"] == "901"
    assert client.get("/api/meetings/100/transcript").json()["segments"][0]["text"].startswith("Ich")
    assert client.get("/api/meetings/nope").status_code == 404


def test_search(client):
    login(client)
    hits = client.get("/api/search", params={"q": "Badi Budget"}).json()
    assert hits[0]["id"] == "c"
    only_pr = client.get("/api/search", params={"q": "Postulat", "types": "protokoll"}).json()
    assert {h["source_type"] for h in only_pr} == {"protokoll"}


def test_chat_streaming_is_grounded_and_saved(client):
    login(client)
    chat = client.post("/api/chats", json={}).json()
    r = client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Was wurde zur Einheitsgemeinde gesagt?"})
    events = [json.loads(l) for l in r.text.splitlines()]
    assert events[0]["type"] == "token"
    final = events[-1]
    assert final["type"] == "final"
    assert "Meinung" not in final["message"]["content"]     # uncited sentence removed
    assert final["message"]["removed"] == 1
    assert final["message"]["sources"][0]["n"] == 1
    saved = client.get(f"/api/chats/{chat['id']}").json()
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant"]
    assert saved["title"].startswith("Was wurde")


def test_projects_flow_and_isolation(client):
    login(client)
    p = client.post("/api/projects", json={"title": "Bericht Schulraum", "category": "Bildung"}).json()
    client.post(f"/api/projects/{p['id']}/items", json={
        "kind": "excerpt", "title": "Votum zur Einheitsgemeinde",
        "ref": {"meeting_id": "100", "meeting_title": "Demo-Sitzung", "date": "2026-09-07", "start": 600,
                "url": "https://youtube.com/x"}})
    assert client.post(f"/api/projects/{p['id']}/items", json={"kind": "bogus", "title": "x"}).status_code == 400
    client.patch(f"/api/projects/{p['id']}", json={"report": "Entwurf des Berichts."})
    full = client.get(f"/api/projects/{p['id']}").json()
    assert full["report"] == "Entwurf des Berichts." and len(full["items"]) == 1
    md = client.get(f"/api/projects/{p['id']}/export").text
    assert "# Bericht Schulraum" in md and "Video 0:10:00" in md

    fa = client.post("/api/projects/from-agenda", json={"meeting_id": "100", "number": "2"}).json()
    assert [i["kind"] for i in fa["items"]] == ["agenda", "document"]

    # Ben cannot see or modify Anna's project
    login(client, "ben@example.org", "geheim456")
    assert client.get("/api/projects").json() == []
    assert client.get(f"/api/projects/{p['id']}").status_code == 404
    assert client.post(f"/api/projects/{p['id']}/items", json={"kind": "note", "title": "x"}).status_code == 404


def test_doc_chunks_types():
    doc = {"doc_id": "901", "title": "Postulat", "url": "https://e/_doc/901", "doc_type": "PO",
           "meetings": ["100"], "pages": [{"page": 1, "text": "Text des Postulats."}]}
    ch = doc_chunks(doc, {"100": MEETING}, 1000)
    assert ch[0]["source_type"] == "dokument" and ch[0]["meeting_ids"] == ["100"]
    assert ch[0]["url"].endswith("#page=1")


def test_announced_numbers():
    assert announced_numbers("Wir kommen zu Traktandum 5, dem Postulat") == {5}
    assert announced_numbers("Traktandum Nummer drei") == {3}


def test_align_chapters_monotonic_and_uses_announcements():
    agenda = [{"number": "1", "title": "Mitteilungen"}, {"number": "2", "title": "Budget"},
              {"number": "3", "title": "Schulhaus"}]
    windows = [{"start": i * 60, "end": (i + 1) * 60, "text": t} for i, t in enumerate([
        "Begrüssung", "Mitteilungen des Rates", "Wir kommen zu Traktandum 2", "Budget Debatte",
        "Budget Abstimmung", "Traktandum 3 Schulhaus", "Schulhaus Diskussion"])]
    sim = np.zeros((3, 7))
    sim[2, 1] = 0.9  # misleading similarity before item 2 - must be ignored by ordering
    ch = align_chapters(agenda, windows, sim)
    assert [c["start"] for c in ch] == [0.0, 120, 300]
    assert [c["confidence"] for c in ch] == ["estimated", "announced", "announced"]
    assert ch[0]["end"] == 120 and ch[-1]["end"] == 420


# ---------------------------------------------------------------- translation

def test_translation_keeps_citations_and_caches(tmp_path):
    from gr_rag.translate import TranslationCache, markers_ok, parse_blocks, translate

    calls = []

    def fake(msgs):
        calls.append(1)
        body = msgs[-1]["content"]
        yield body.replace("Der Kredit wurde angenommen", "The credit was approved") \
                  .replace("Ohne Quelle [2]", "Without source")   # drops a marker -> must be rejected

    cache = TranslationCache(tmp_path / "t.db")
    texts = ["Der Kredit wurde angenommen [1].", "Ohne Quelle [2]", ""]
    out, ok = translate(texts, "en", cache, fake)
    assert out[0] == "The credit was approved [1]." and ok[0]
    assert out[1] == "Ohne Quelle [2]" and not ok[1]            # original kept, flagged
    assert ok[2]
    translate(texts[:1], "en", cache, fake)
    assert len(calls) == 1                                       # cached
    assert markers_ok("a [1][2]", "b [2][1]") and not markers_ok("a [1]", "b")
    assert parse_blocks("### 1\nA\n### 2\nB", 2) == ["A", "B"]


def test_translate_endpoint_and_english_answers(client):
    login(client)
    r = client.post("/api/translate", json={"texts": ["Hallo [1]."], "target": "en"})
    assert r.status_code == 200 and len(r.json()["texts"]) == 1
    assert client.post("/api/translate", json={"texts": ["x"], "target": "xx"}).status_code == 400
    chat = client.post("/api/chats", json={}).json()
    r = client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Wetter?", "lang": "en"})
    assert json.loads(r.text.splitlines()[-1])["type"] == "final"


def test_english_refusal():
    from gr_rag.rag import NO_INFO_EN, RAG
    from test_pipeline import make_retriever
    rag = RAG(make_retriever(), chat_fn=lambda m: iter(["x"]))
    rag.min_score = 0.99
    assert rag.ask("Weather tomorrow?", lang="en").text == NO_INFO_EN


def test_english_answers_not_flagged_for_low_overlap():
    from gr_rag.index import Hit
    from gr_rag.rag import validate
    from test_pipeline import CHUNKS
    hits = [Hit(c, 1.0, 0.9) for c in CHUNKS]
    assert validate("The council discussed the merger [1].", hits, "en").sources[0].support == 1.0
    assert validate("Völlig andere Wörter hier [1].", hits, "de").sources[0].support < 0.3


def test_message_language_stored(client):
    login(client)
    chat = client.post("/api/chats", json={}).json()
    client.post(f"/api/chats/{chat['id']}/messages", json={"content": "Einheitsgemeinde?", "lang": "en"})
    msgs = client.get(f"/api/chats/{chat['id']}").json()["messages"]
    assert [m["lang"] for m in msgs] == ["en", "en"]
