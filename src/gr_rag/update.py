"""`gr-rag update`: bring the archive up to date in one command.

Every step only processes what is missing, so re-running is cheap and safe:

  1. scrape      meeting list + detail pages (new meetings, new video links/documents)
  2. audio       download audio for meetings with a video but no transcript yet
  3. transcribe  Whisper - only if a GPU is available (or --transcribe-on-cpu);
                 otherwise reports which meetings still need the GPU (cluster/update.sh)
  4. documents   minutes and other PDFs -> text
  5. index       chunks + embeddings, only new text is embedded (needs Ollama)
  6. summaries   chapters / cited summaries / outcomes for meetings without one (needs Ollama)
  7. cleanup     optionally delete audio of fully transcribed meetings

Steps 1-4 need internet; 5-6 need Ollama. Use --only/--skip to run part of it.
"""
from __future__ import annotations

import json
import time

import requests

from .config import load_config, paths

STEPS = ["scrape", "audio", "transcribe", "documents", "index", "summaries", "cleanup"]


def _ollama_ok() -> bool:
    try:
        requests.get(f"{load_config()['retrieval']['ollama_url']}/api/tags", timeout=3).raise_for_status()
        return True
    except Exception:
        return False


def _gpu_ok() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _transcript_state(mid: str) -> str:
    f = paths().transcripts / f"{mid}.json"
    if not f.exists():
        return "missing"
    return "done" if json.loads(f.read_text(encoding="utf-8")).get("complete") else "partial"


def run_update(since: str | None = None, only: list[str] | None = None, skip: list[str] | None = None,
               transcribe_on_cpu: bool = False, delete_audio: bool = False) -> dict:
    from .download import audio_file, download_audio, download_documents
    from .scrape import load_meetings, scrape

    steps = [s for s in STEPS if (not only or s in only) and s not in (skip or [])]
    if not delete_audio and "cleanup" in steps and not (only and "cleanup" in only):
        steps.remove("cleanup")
    p = paths()
    report: dict = {"steps": steps, "started": time.strftime("%Y-%m-%d %H:%M")}
    before = {m["id"] for m in load_meetings()} if p.meetings.exists() else set()

    def head(name: str):
        print(f"\n=== {name} " + "=" * (60 - len(name)))

    # 1 ---------------------------------------------------------------- scrape
    if "scrape" in steps:
        head("1/7 Sitzungen abrufen")
        if since is None and before:   # keep the range the archive already covers
            since = min((m["date"] for m in load_meetings() if m.get("date")), default=None)
        scrape(only_past=True, since=since or "2023-01-01")
    meetings = [m for m in load_meetings() if not m.get("cancelled")]
    report["new_meetings"] = [f"{m['date']} {m['title']}" for m in meetings if m["id"] not in before] if before else []

    # 2 ---------------------------------------------------------------- audio
    need_audio = [m["id"] for m in meetings if m.get("youtube_id") and _transcript_state(m["id"]) != "done"
                  and not audio_file(m["id"])]
    if "audio" in steps and need_audio:
        head(f"2/7 Audio herunterladen ({len(need_audio)})")
        try:
            download_audio(need_audio)
        except Exception as e:
            print(f"  ! Audio-Download fehlgeschlagen: {e}")
            report["audio_error"] = str(e)

    # 3 ---------------------------------------------------------------- transcribe
    pending = [m["id"] for m in meetings if m.get("youtube_id") and _transcript_state(m["id"]) != "done"
               and audio_file(m["id"])]
    report["transcribed"] = []
    if "transcribe" in steps and pending:
        head(f"3/7 Transkribieren ({len(pending)})")
        if _gpu_ok() or transcribe_on_cpu:
            from .transcribe import transcribe_all
            transcribe_all(pending)
            report["transcribed"] = [mid for mid in pending if _transcript_state(mid) == "done"]
        else:
            print("  Keine GPU gefunden - Transkription übersprungen.")
            print("  Auf dem UZH-Cluster ausführen: bash cluster/update.sh")
            print("  (oder hier trotzdem, sehr langsam: gr-rag update --transcribe-on-cpu)")
    report["still_untranscribed"] = [m["id"] for m in meetings
                                     if m.get("youtube_id") and _transcript_state(m["id"]) != "done"]

    # 4 ---------------------------------------------------------------- documents
    if "documents" in steps:
        head("4/7 Protokolle und Dokumente")
        download_documents()

    # 5/6 -------------------------------------------------------------- index + summaries (Ollama)
    needs_ollama = [s for s in ("index", "summaries") if s in steps]
    ollama = _ollama_ok() if needs_ollama else False
    if needs_ollama and not ollama:
        print("\n  ! Ollama läuft nicht (ollama serve) - Suchindex und Zusammenfassungen übersprungen.")
        report["ollama_missing"] = True
    if "index" in steps and ollama:
        head("5/7 Suchindex aktualisieren")
        from .chunk import build_chunks
        from .index import build_index
        report["index"] = build_index(build_chunks())
    if "summaries" in steps and ollama and (p.index / "chunks.jsonl").exists():
        head("6/7 Zusammenfassungen für neue Sitzungen")
        from .summarize import summarize_all
        todo = [m["id"] for m in meetings if not (p.summaries / f"{m['id']}.json").exists()
                and (_transcript_state(m["id"]) == "done"
                     or any(d["doc_type"] == "PR" for d in m.get("documents", [])))]
        if todo:
            summarize_all(todo)
        report["summarized"] = todo

    # 7 ---------------------------------------------------------------- cleanup
    if "cleanup" in steps:
        head("7/7 Audio aufräumen")
        removed = 0
        for m in meetings:
            f = audio_file(m["id"])
            if f and _transcript_state(m["id"]) == "done":
                f.unlink()
                removed += 1
        print(f"  {removed} Audiodateien gelöscht (Transkripte sind vorhanden).")
        report["audio_deleted"] = removed

    # ---------------------------------------------------------------- report
    head("Zusammenfassung")
    print(f"  Neue Sitzungen:        {len(report['new_meetings'])}" +
          "".join(f"\n    - {x}" for x in report["new_meetings"]))
    print(f"  Neu transkribiert:     {len(report['transcribed'])}")
    print(f"  Noch ohne Transkript:  {len(report['still_untranscribed'])}" +
          ("  -> auf dem Cluster: bash cluster/update.sh" if report["still_untranscribed"] else ""))
    if "index" in report:
        print(f"  Suchindex:             {report['index']['total']} Abschnitte ({report['index']['embedded']} neu)")
    if report.get("summarized") is not None:
        print(f"  Neue Zusammenfassungen: {len(report['summarized'])}")
    if report.get("ollama_missing"):
        print("  Hinweis: Ollama starten und 'gr-rag update --only index summaries' ausführen.")
    (p.data / "last_update.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report
