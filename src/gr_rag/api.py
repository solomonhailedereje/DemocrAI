"""FastAPI backend for the DemocrAI Ratsarchiv frontend.

Run:  gr-rag serve            (serves the API and, if built, frontend/dist)
Dev:  uvicorn gr_rag.api:create_app --factory --reload   +   cd frontend && npm run dev
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .chunk import fmt_ts
from .config import ROOT, paths
from .download import doc_id, load_doc, meeting_documents
from .rag import RAG, Answer
from .store import Store

COOKIE = "ratsarchiv_session"


# --------------------------------------------------------------------------- request models

class LoginIn(BaseModel):
    email: str
    password: str


class Filters(BaseModel):
    source_types: list[str] | None = None
    date_from: str | None = None
    date_to: str | None = None
    meeting_id: str | None = None


class AskIn(BaseModel):
    content: str
    filters: Filters | None = None


class ChatIn(BaseModel):
    title: str | None = None
    meeting_id: str | None = None


class ProjectIn(BaseModel):
    title: str
    category: str = "Allgemein"
    description: str = ""


class ProjectPatch(BaseModel):
    title: str | None = None
    category: str | None = None
    description: str | None = None
    report: str | None = None


class ItemIn(BaseModel):
    kind: str
    title: str
    ref: dict = {}
    note: str = ""


class ItemPatch(BaseModel):
    note: str


class FromAgendaIn(BaseModel):
    meeting_id: str
    number: str
    category: str = "Allgemein"


# --------------------------------------------------------------------------- data access

def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def meetings_by_id() -> dict[str, dict]:
    f = paths().meetings
    return _cached_meetings(str(f), f.stat().st_mtime if f.exists() else 0)


@lru_cache(maxsize=2)
def _cached_meetings(path: str, mtime: float) -> dict[str, dict]:
    data = _read_json(Path(path)) or []
    return {m["id"]: m for m in data}


def meeting_flags(m: dict) -> dict:
    p = paths()
    t = _read_json(p.transcripts / f"{m['id']}.json")
    return {
        "has_video": bool(m.get("youtube_id")),
        "has_transcript": bool(t and t.get("segments")),
        "has_protokoll": any(d["doc_type"] == "PR" for d in m.get("documents", [])),
        "has_summary": (p.summaries / f"{m['id']}.json").exists(),
    }


def source_view(chunk: dict) -> dict:
    """What the frontend needs to render a source card / deep link."""
    keep = ("id", "source_type", "meeting_id", "meeting_title", "date", "text", "start", "end",
            "label", "url", "doc_id", "doc_title", "page")
    return {k: chunk[k] for k in keep if k in chunk}


def answer_view(ans: Answer) -> dict:
    return {"text": ans.text, "grounded": ans.grounded,
            "removed": len(ans.removed_sentences),
            "sources": [{"n": s.n, "support": s.support, **source_view(s.chunk)} for s in ans.sources]}


# --------------------------------------------------------------------------- app factory

def create_app(store: Store | None = None, rag_factory=None) -> FastAPI:
    app = FastAPI(title="DemocrAI Ratsarchiv API")
    app.state.store = store or Store(paths().db)
    app.state.rag = None
    rag_factory = rag_factory or RAG

    def get_rag() -> RAG:
        if app.state.rag is None:
            try:
                app.state.rag = rag_factory()
            except FileNotFoundError as e:
                raise HTTPException(503, f"Suchindex fehlt: {e}")
        return app.state.rag

    def user(ratsarchiv_session: str | None = Cookie(default=None)) -> dict:
        u = app.state.store.user_for_token(ratsarchiv_session)
        if not u:
            raise HTTPException(401, "Nicht angemeldet")
        return u

    S = lambda: app.state.store  # noqa: E731

    # ------------------------------------------------------------------ auth
    @app.post("/api/auth/login")
    def login(body: LoginIn, response: Response):
        token = S().login(body.email, body.password)
        if not token:
            raise HTTPException(401, "E-Mail oder Passwort falsch")
        response.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=14 * 86400)
        return S().user_for_token(token)

    @app.post("/api/auth/logout")
    def logout(response: Response, ratsarchiv_session: str | None = Cookie(default=None)):
        if ratsarchiv_session:
            S().logout(ratsarchiv_session)
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(u: dict = Depends(user)):
        return u

    # ------------------------------------------------------------------ meetings
    @app.get("/api/meetings")
    def list_meetings(u: dict = Depends(user)):
        out = []
        for m in meetings_by_id().values():
            out.append({k: m.get(k) for k in ("id", "title", "date", "start", "end", "cancelled", "youtube_id")}
                       | {"n_agenda": len(m.get("agenda") or [])} | meeting_flags(m))
        return sorted(out, key=lambda m: m["date"] or "", reverse=True)

    @app.get("/api/meetings/{mid}")
    def get_meeting(mid: str, u: dict = Depends(user)):
        m = meetings_by_id().get(mid)
        if not m:
            raise HTTPException(404, "Sitzung nicht gefunden")
        p = paths()
        docs = []
        for d in meeting_documents(m):
            did = doc_id(d["url"])
            rec = load_doc(did)
            docs.append({**d, "doc_id": did, "has_text": bool(rec and rec["pages"]),
                         "n_pages": len(rec["pages"]) if rec else None,
                         "has_summary": (p.summaries / "docs" / f"{did}.json").exists()})
        agenda = [{**a, "documents": [{**d, "doc_id": doc_id(d["url"])} for d in a.get("documents", [])]}
                  for a in m.get("agenda", [])]
        summary = _read_json(p.summaries / f"{mid}.json")
        return {**m, "agenda": agenda, "documents": docs, "summary": summary, **meeting_flags(m)}

    @app.get("/api/meetings/{mid}/transcript")
    def get_transcript(mid: str, u: dict = Depends(user)):
        t = _read_json(paths().transcripts / f"{mid}.json")
        if not t:
            raise HTTPException(404, "Kein Transkript")
        return {"complete": t.get("complete", False), "segments": t["segments"]}

    # ------------------------------------------------------------------ search
    @app.get("/api/search")
    def search(q: str, types: str | None = None, date_from: str | None = None, date_to: str | None = None,
               meeting_id: str | None = None, limit: int = 20, u: dict = Depends(user)):
        if not q.strip():
            return []
        hits = get_rag().retriever.search(
            q, top_k=min(limit, 50),
            source_types=set(types.split(",")) if types else None,
            date_from=date_from, date_to=date_to,
            meeting_ids={meeting_id} if meeting_id else None)
        return [{"score": round(h.score, 3), "similarity": round(h.dense, 3), **source_view(h.chunk)} for h in hits]

    # ------------------------------------------------------------------ documents
    @app.get("/api/documents/{did}/summary")
    def get_doc_summary(did: str, u: dict = Depends(user)):
        s = _read_json(paths().summaries / "docs" / f"{did}.json")
        if not s:
            raise HTTPException(404, "Noch keine Zusammenfassung")
        return s

    @app.post("/api/documents/{did}/summary")
    def make_doc_summary(did: str, refresh: bool = False, u: dict = Depends(user)):
        from .summarize import doc_summary
        if not load_doc(did):
            raise HTTPException(404, "Dokument nicht heruntergeladen (gr-rag documents)")
        rag = get_rag()
        return doc_summary(rag.retriever, did, rag.chat_fn, refresh=refresh)

    # ------------------------------------------------------------------ chats
    @app.get("/api/chats")
    def list_chats(u: dict = Depends(user)):
        return S().list_chats(u["id"])

    @app.post("/api/chats")
    def create_chat(body: ChatIn, u: dict = Depends(user)):
        return S().create_chat(u["id"], body.title or "Neuer Chat", body.meeting_id)

    @app.get("/api/chats/{cid}")
    def get_chat(cid: int, u: dict = Depends(user)):
        c = S().get_chat(u["id"], cid)
        if not c:
            raise HTTPException(404)
        return c

    @app.patch("/api/chats/{cid}")
    def rename_chat(cid: int, body: ChatIn, u: dict = Depends(user)):
        S().rename_chat(u["id"], cid, body.title or "Chat")
        return S().get_chat(u["id"], cid)

    @app.delete("/api/chats/{cid}")
    def delete_chat(cid: int, u: dict = Depends(user)):
        S().delete_chat(u["id"], cid)
        return {"ok": True}

    @app.post("/api/chats/{cid}/messages")
    def ask(cid: int, body: AskIn, u: dict = Depends(user)):
        chat = S().get_chat(u["id"], cid)
        if not chat:
            raise HTTPException(404)
        rag = get_rag()
        f = body.filters or Filters()
        meeting_id = f.meeting_id or chat.get("meeting_id")
        history = [{"role": m["role"], "content": m["content"]} for m in chat["messages"]]
        S().add_message(cid, "user", body.content)
        if not chat["messages"] and chat["title"] == "Neuer Chat":
            S().rename_chat(u["id"], cid, body.content[:60])

        def gen() -> Iterator[str]:
            final = None
            try:
                for item in rag.stream(body.content, history,
                                       source_types=set(f.source_types) if f.source_types else None,
                                       date_from=f.date_from, date_to=f.date_to,
                                       meeting_ids={meeting_id} if meeting_id else None):
                    if isinstance(item, Answer):
                        final = item
                    else:
                        yield json.dumps({"type": "token", "text": item}) + "\n"
            except Exception as e:  # e.g. Ollama not running
                yield json.dumps({"type": "error", "message": f"{type(e).__name__}: {e}"}) + "\n"
                return
            view = answer_view(final)
            msg = S().add_message(cid, "assistant", view["text"], view["sources"], view["grounded"])
            yield json.dumps({"type": "final", "message": {**msg, "removed": view["removed"]}}) + "\n"

        return StreamingResponse(gen(), media_type="application/x-ndjson")

    # ------------------------------------------------------------------ projects
    @app.get("/api/projects")
    def list_projects(u: dict = Depends(user)):
        return S().list_projects(u["id"])

    @app.post("/api/projects")
    def create_project(body: ProjectIn, u: dict = Depends(user)):
        return S().create_project(u["id"], body.title, body.category, body.description)

    @app.get("/api/projects/{pid}")
    def get_project(pid: int, u: dict = Depends(user)):
        p = S().get_project(u["id"], pid)
        if not p:
            raise HTTPException(404)
        return p

    @app.patch("/api/projects/{pid}")
    def update_project(pid: int, body: ProjectPatch, u: dict = Depends(user)):
        p = S().update_project(u["id"], pid, **body.model_dump())
        if not p:
            raise HTTPException(404)
        return p

    @app.delete("/api/projects/{pid}")
    def delete_project(pid: int, u: dict = Depends(user)):
        S().delete_project(u["id"], pid)
        return {"ok": True}

    @app.post("/api/projects/{pid}/items")
    def add_item(pid: int, body: ItemIn, u: dict = Depends(user)):
        try:
            it = S().add_item(u["id"], pid, body.kind, body.title, body.ref, body.note)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not it:
            raise HTTPException(404)
        return it

    @app.patch("/api/projects/{pid}/items/{iid}")
    def update_item(pid: int, iid: int, body: ItemPatch, u: dict = Depends(user)):
        S().update_item(u["id"], pid, iid, body.note)
        return {"ok": True}

    @app.delete("/api/projects/{pid}/items/{iid}")
    def delete_item(pid: int, iid: int, u: dict = Depends(user)):
        S().delete_item(u["id"], pid, iid)
        return {"ok": True}

    @app.post("/api/projects/from-agenda")
    def project_from_agenda(body: FromAgendaIn, u: dict = Depends(user)):
        m = meetings_by_id().get(body.meeting_id)
        item = next((a for a in (m or {}).get("agenda", []) if a["number"] == body.number), None)
        if not item:
            raise HTTPException(404, "Traktandum nicht gefunden")
        title = item["title"].split(" / ")[0][:120]
        p = S().create_project(u["id"], title, body.category,
                               f"Aus Traktandum {item['number']} der {m['title']} vom {m['date']}")
        S().add_item(u["id"], p["id"], "agenda", f"Traktandum {item['number']}: {item['title']}",
                     {"meeting_id": m["id"], "number": item["number"], "meeting_title": m["title"], "date": m["date"]})
        for d in item.get("documents", []):
            S().add_item(u["id"], p["id"], "document", d["title"],
                         {"doc_id": doc_id(d["url"]), "url": d["url"], "meeting_id": m["id"]})
        return S().get_project(u["id"], p["id"])

    @app.get("/api/projects/{pid}/export", response_class=PlainTextResponse)
    def export_project(pid: int, u: dict = Depends(user)):
        p = S().get_project(u["id"], pid)
        if not p:
            raise HTTPException(404)
        return export_markdown(p)

    # ------------------------------------------------------------------ frontend (built)
    dist = ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str, request: Request):
            f = dist / path
            if path and f.is_file():
                return FileResponse(f)
            return FileResponse(dist / "index.html")

    return app


def export_markdown(p: dict) -> str:
    lines = [f"# {p['title']}", "", f"*Kategorie: {p['category']}*", ""]
    if p["description"]:
        lines += [p["description"], ""]
    if p["report"].strip():
        lines += ["## Bericht", "", p["report"].strip(), ""]
    lines += ["## Gesammelte Quellen", ""]
    for it in p["items"]:
        r = it["ref"]
        line = f"- **{it['title']}**"
        if it["kind"] == "excerpt" and r.get("start") is not None:
            line += f" – {r.get('meeting_title', '')} {r.get('date', '')}, Video {fmt_ts(r['start'])}"
        if r.get("url"):
            line += f" – {r['url']}"
        lines.append(line)
        if it["kind"] == "answer" and r.get("text"):
            lines.append(f"  > {r['text']}")
            for s in r.get("sources", []):
                lines.append(f"  > [{s['n']}] {s.get('meeting_title', '')} {s.get('date', '')} – "
                             f"{s.get('label', '')} – {s.get('url', '')}")
        if it["note"]:
            lines.append(f"  Notiz: {it['note']}")
    return "\n".join(lines) + "\n"
