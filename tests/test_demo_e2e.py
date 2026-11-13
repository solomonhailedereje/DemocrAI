"""End-to-end: demo data -> chunks -> index -> chapters/summaries -> API -> grounded answers."""
import json

from fastapi.testclient import TestClient


def test_demo_end_to_end(tmp_path, monkeypatch):
    from gr_rag.demo import build_demo, extractive_chat, hash_embed

    build_demo(tmp_path)        # sets GR_RAG_DATA
    s = json.loads((tmp_path / "summaries" / "9001.json").read_text())
    assert [c["confidence"] for c in s["chapters"]] == ["announced"] * 4
    starts = [c["start"] for c in s["chapters"]]
    assert starts == sorted(starts)
    assert any("22 zu 12" in o["text"] for o in s["outcomes"])
    # every generated sentence carries a citation that points to a stored source
    for it in s["items"]:
        for part in (it["video"], it["protokoll"]):
            if part:
                assert part["sources"] and "[1]" in part["text"]

    from gr_rag.api import create_app
    from gr_rag.index import Retriever
    from gr_rag.rag import RAG

    def factory():
        rag = RAG(Retriever(embed_fn=hash_embed), chat_fn=lambda m: extractive_chat(m, delay=0))
        rag.min_score = 0.12
        return rag

    c = TestClient(create_app(rag_factory=factory))
    assert c.post("/api/auth/login", json={"email": "demo@example.org", "password": "demo1234"}).status_code == 200
    m = c.get("/api/meetings/9001").json()
    assert m["summary"]["chapters"] and len(m["documents"]) == 4

    chat = c.post("/api/chats", json={}).json()
    ev = [json.loads(l) for l in c.post(f"/api/chats/{chat['id']}/messages",
                                        json={"content": "Was wurde zu den Velowegen gesagt?"}).text.splitlines()]
    final = ev[-1]["message"]
    assert final["grounded"] and "Velo" in final["content"] and final["sources"]

    chat2 = c.post("/api/chats", json={}).json()
    ev = [json.loads(l) for l in c.post(f"/api/chats/{chat2['id']}/messages",
                                        json={"content": "Wie ist das Wetter morgen?"}).text.splitlines()]
    assert not ev[-1]["message"]["grounded"] and ev[-1]["message"]["sources"] == []

    doc = next(d for d in m["documents"] if d["doc_type"] == "PO")
    ds = c.post(f"/api/documents/{doc['doc_id']}/summary").json()
    assert ds["blocks"] and ds["blocks"][0]["sources"]
