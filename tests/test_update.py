"""gr-rag update: step order, skipping of finished work, incremental index."""
import json

import numpy as np

from test_api import MEETING


def fake_embed(texts):
    v = np.array([[len(t), t.count("e") + 1, 1.0] for t in texts], dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def test_incremental_index_only_embeds_new_chunks(tmp_path, monkeypatch):
    monkeypatch.setenv("GR_RAG_DATA", str(tmp_path))
    from gr_rag.index import build_index
    calls = []

    def counting(texts):
        calls.append(len(texts))
        return fake_embed(texts)

    a = [{"id": "x", "text": "eins"}, {"id": "y", "text": "zwei"}]
    assert build_index(a, counting)["embedded"] == 2
    b = a + [{"id": "z", "text": "drei"}]
    assert build_index(b, counting)["embedded"] == 1
    c = [{"id": "x", "text": "eins GEÄNDERT"}, *b[1:]]
    assert build_index(c, counting)["embedded"] == 1
    assert calls == [2, 1, 1]
    vecs = np.load(tmp_path / "index" / "embeddings.npy")
    assert np.allclose(vecs, fake_embed([x["text"] for x in c]))


def test_update_runs_steps_and_skips_done_work(tmp_path, monkeypatch):
    monkeypatch.setenv("GR_RAG_DATA", str(tmp_path))
    import gr_rag.download as dl
    import gr_rag.index as idx
    import gr_rag.scrape as sc
    import gr_rag.summarize as sm
    import gr_rag.transcribe as tr
    import gr_rag.update as up

    old = {**MEETING, "id": "100"}
    new = {**MEETING, "id": "200", "date": "2026-10-05", "title": "Neue Sitzung", "youtube_id": "vid200"}
    (tmp_path / "meetings.json").write_text(json.dumps([old]))
    (tmp_path / "transcripts").mkdir(exist_ok=True)
    (tmp_path / "transcripts" / "100.json").write_text(json.dumps(
        {"meeting_id": "100", "complete": True, "segments": [{"start": 0, "end": 5, "text": "Alt."}]}))

    log = []
    monkeypatch.setattr(sc, "scrape", lambda only_past, since: (log.append(("scrape", since)),
                        (tmp_path / "meetings.json").write_text(json.dumps([new, old]))))

    def fake_audio(ids):
        log.append(("audio", ids))
        for i in ids:
            (tmp_path / "audio" / f"{i}.m4a").write_bytes(b"x")
    monkeypatch.setattr(dl, "download_audio", fake_audio)
    monkeypatch.setattr(dl, "download_documents", lambda only=None: log.append(("documents",)))

    def fake_transcribe(ids):
        log.append(("transcribe", ids))
        for i in ids:
            (tmp_path / "transcripts" / f"{i}.json").write_text(json.dumps(
                {"meeting_id": i, "complete": True, "segments": [{"start": 0, "end": 5, "text": "Neu."}]}))
    monkeypatch.setattr(tr, "transcribe_all", fake_transcribe)
    monkeypatch.setattr(up, "_gpu_ok", lambda: True)
    monkeypatch.setattr(up, "_ollama_ok", lambda: True)
    monkeypatch.setattr(idx, "embed", fake_embed)
    monkeypatch.setattr(sm, "summarize_all", lambda ids: log.append(("summaries", ids)))

    r = up.run_update(delete_audio=True)
    assert log[0] == ("scrape", "2026-09-07")          # keeps the existing date range
    assert ("audio", ["200"]) in log                     # only the new meeting
    assert ("transcribe", ["200"]) in log
    assert ("summaries", ["200", "100"]) in log or ("summaries", ["100", "200"]) in log
    assert r["new_meetings"] == ["2026-10-05 Neue Sitzung"]
    assert r["still_untranscribed"] == []
    assert r["audio_deleted"] == 1 and not (tmp_path / "audio" / "200.m4a").exists()
    assert r["index"]["embedded"] == r["index"]["total"] > 0

    # second run: nothing new to do
    log.clear()
    r2 = up.run_update(skip=["scrape"])
    assert not any(e[0] in ("audio", "transcribe") for e in log)
    assert r2["index"]["embedded"] == 0


def test_update_without_gpu_or_ollama_reports_instead_of_failing(tmp_path, monkeypatch):
    monkeypatch.setenv("GR_RAG_DATA", str(tmp_path))
    import gr_rag.download as dl
    import gr_rag.update as up
    new = {**MEETING, "id": "300", "youtube_id": "v"}
    (tmp_path / "meetings.json").write_text(json.dumps([new]))
    (tmp_path / "audio").mkdir(exist_ok=True)
    (tmp_path / "audio" / "300.m4a").write_bytes(b"x")
    monkeypatch.setattr(dl, "download_documents", lambda only=None: None)
    monkeypatch.setattr(up, "_gpu_ok", lambda: False)
    monkeypatch.setattr(up, "_ollama_ok", lambda: False)
    r = up.run_update(skip=["scrape", "audio"])
    assert r["still_untranscribed"] == ["300"] and r["ollama_missing"]
    assert json.loads((tmp_path / "last_update.json").read_text())["still_untranscribed"] == ["300"]
