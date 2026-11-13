"""Command line entry point:  gr-rag <command>

Pipeline (typical order):
  gr-rag scrape --since 2023-01-01   # meeting list, video links, documents, agenda
  gr-rag download-audio              # YouTube -> data/audio/<id>.m4a  (~30 MB per hour)
  gr-rag convert-model               # one-off: Whisper -> CTranslate2 (for faster-whisper)
  gr-rag transcribe                  # data/transcripts/<id>.json  (GPU recommended, resumable)
  gr-rag documents                   # all meeting PDFs -> per-page text (--protokolle-only)
  gr-rag build-index                 # chunks + embeddings (needs Ollama running)
  gr-rag summarize                   # chapters, cited summaries, vote outcomes per meeting

Web app:
  gr-rag add-user anna@duebendorf.ch "Anna Muster"   # prompts for a password
  gr-rag serve                       # http://localhost:8000

Checks:
  gr-rag status | gr-rag search "..." | gr-rag ask "..."
"""
from __future__ import annotations

import argparse


def main() -> None:
    ap = argparse.ArgumentParser(prog="gr-rag", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scrape")
    sc.add_argument("--include-future", action="store_true")
    sc.add_argument("--since", help="only meetings on/after this date, e.g. 2022-01-01")
    for name in ("download-audio", "transcribe"):
        sub.add_parser(name).add_argument("--ids", nargs="*", help="only these meeting ids")
    sub.add_parser("convert-model")
    sub.add_parser("prefetch-model")
    sub.add_parser("documents").add_argument("--protokolle-only", action="store_true")
    sub.add_parser("protokolle", help="alias for: documents --protokolle-only")
    sub.add_parser("build-index")
    sm = sub.add_parser("summarize")
    sm.add_argument("--ids", nargs="*")
    sm.add_argument("--refresh", action="store_true")
    sub.add_parser("status")
    s = sub.add_parser("search"); s.add_argument("query")
    a = sub.add_parser("ask"); a.add_argument("question")
    au = sub.add_parser("add-user"); au.add_argument("email"); au.add_argument("name")
    sp = sub.add_parser("set-password"); sp.add_argument("email")
    sub.add_parser("list-users")
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    dm = sub.add_parser("demo", help="fictional demo data + offline models, then serve")
    dm.add_argument("--port", type=int, default=8000)
    dm.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    if args.cmd == "scrape":
        from .scrape import scrape
        scrape(only_past=not args.include_future, since=args.since)
    elif args.cmd == "download-audio":
        from .download import download_audio
        download_audio(args.ids)
    elif args.cmd == "convert-model":
        from .transcribe import convert_model
        convert_model()
    elif args.cmd == "prefetch-model":
        from .transcribe import prefetch_model
        prefetch_model()
    elif args.cmd == "transcribe":
        from .transcribe import transcribe_all
        transcribe_all(args.ids)
    elif args.cmd in ("documents", "protokolle"):
        from .download import download_documents
        only = {"PR"} if args.cmd == "protokolle" or args.protokolle_only else None
        download_documents(only)
    elif args.cmd == "build-index":
        from collections import Counter
        from .chunk import build_chunks
        from .index import build_index
        chunks = build_chunks()
        print("  ", dict(Counter(c["source_type"] for c in chunks)))
        build_index(chunks)
    elif args.cmd == "summarize":
        from .summarize import summarize_all
        summarize_all(args.ids, args.refresh)
    elif args.cmd == "status":
        _status()
    elif args.cmd == "search":
        from .index import Retriever
        for h in Retriever().search(args.query):
            c = h.chunk
            print(f"{h.score:.3f} (cos {h.dense:.3f})  {c['date']} {c['label']}  {c['url']}\n    {c['text'][:200]}\n")
    elif args.cmd == "ask":
        from .rag import RAG
        ans = RAG().ask(args.question)
        print("\n" + ans.text + "\n")
        for s in ans.sources:
            c = s.chunk
            print(f"[{s.n}] {c['meeting_title']} ({c['date']}) – {c['label']}\n    {c['url']}")
    elif args.cmd in ("add-user", "set-password", "list-users"):
        _users(args)
    elif args.cmd == "serve":
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(), host=args.host, port=args.port)
    elif args.cmd == "demo":
        import shutil
        import uvicorn
        from .demo import DEMO_DIR, build_demo, demo_app
        if args.rebuild and DEMO_DIR.exists():
            shutil.rmtree(DEMO_DIR)
        if not (DEMO_DIR / "index" / "chunks.jsonl").exists():
            build_demo()
        print(f"Demo: http://127.0.0.1:{args.port}  –  login demo@example.org / demo1234")
        uvicorn.run(demo_app(), host="127.0.0.1", port=args.port)


def _users(args) -> None:
    import getpass
    from .config import paths
    from .store import Store
    store = Store(paths().db)
    if args.cmd == "list-users":
        for u in store.list_users():
            print(f"{u['id']:>3}  {u['email']:<35} {u['name']}")
        return
    pw = getpass.getpass("Passwort (min. 8 Zeichen): ")
    if pw != getpass.getpass("Wiederholen: "):
        raise SystemExit("Passwörter stimmen nicht überein.")
    if args.cmd == "add-user":
        store.add_user(args.email, args.name, pw)
        print(f"Benutzer {args.email} angelegt.")
    else:
        store.set_password(args.email, pw)
        print("Passwort geändert.")


def _status() -> None:
    import json
    from .config import paths
    from .download import audio_file, doc_id
    from .scrape import load_meetings
    p = paths()
    for m in load_meetings():
        if m.get("cancelled"):
            continue
        t = p.transcripts / f"{m['id']}.json"
        tstate = "–"
        if t.exists():
            tstate = "done" if json.loads(t.read_text())["complete"] else "partial"
        pr = [d for d in m.get("documents", []) if d["doc_type"] == "PR"]
        pr_ok = pr and all((p.docs / f"{doc_id(d['url'])}.json").exists() for d in pr)
        print(f"{m['date']}  {m['title']:<32} video={'✓' if m.get('youtube_id') else '✗'} "
              f"audio={'✓' if audio_file(m['id']) else '–'} transcript={tstate:<7} "
              f"protokoll={'✓' if pr_ok else '–'} summary={'✓' if (p.summaries / (m['id'] + '.json')).exists() else '–'}")


if __name__ == "__main__":
    main()
