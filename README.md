# Gemeinderat Dübendorf – grounded Q&A over meeting recordings

Ask questions about Dübendorf city council (Gemeinderat) meetings. Answers come **only**
from (a) Swiss German → Standard German transcripts of the meeting videos and (b) the
official minutes (Protokolle), and every sentence links to its source: the YouTube video
at the exact second, or the PDF page.

```
duebendorf.ch/sitzung ──scrape──► meetings.json (date, YouTube id, Protokoll PDFs, agenda)
        │                                    │
   YouTube audio                        Protokoll PDFs
        │ Whisper (Swiss German)             │ pypdf, per page
        ▼                                    ▼
 timestamped transcript ──► chunks ◄── page-level text
                              │
             bge-m3 embeddings + BM25 (hybrid)      ◄── all local via Ollama
                              │
             Retrieval gate → strict prompt → citation check
                              │
   FastAPI + React web app: Home · Sitzungen · Fragen · Planen (logins, projects)
```

## What's on the site

* ~245 meetings listed, back to 2004. The list is embedded as JSON in the `/sitzung` page.
* **YouTube recordings exist from about 2023 onward** (with gaps): roughly 30 meetings,
  1–4.5 h each. Older meetings have only Protokolle, and those are indexed too.
* Document file names encode their type: `YYYYMMDD-PR-…` = Protokoll, `-TL-` = agenda, `-BS-` = Stadtrat decision.

## How grounding is enforced

The prompt asks the model to stay grounded, and the code enforces it in three places:

1. **Retrieval gate**: if no excerpt has cosine similarity ≥ `min_score`, the app answers
   "Dazu finde ich … keine Angaben" **without calling the LLM**.
2. **Strict prompt**: the model sees only numbered excerpts and must cite `[n]` after every sentence.
3. **Post-check** (`rag.validate`): sentences without a valid citation are **removed**,
   citations to non-existent excerpts are removed, and if nothing cited remains the
   answer becomes the refusal. Only the excerpts actually cited are shown, renumbered.
   Low word-overlap between a sentence and its source is flagged in the UI.

## Setup (macOS, also Intel Macs)

```bash
# Python 3.10–3.12
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[web,transcribe,dev]"

# Ollama for embeddings + LLM (https://ollama.com/download)
ollama pull bge-m3
ollama pull qwen2.5:3b        # 8 GB RAM. With 16 GB try qwen2.5:7b (better German, slower)
```

## Run the pipeline

```bash
gr-rag scrape --since 2023-01-01   # or no --since for all Protokolle back to 2004 (~5 min)
gr-rag download-audio              # ~30 MB per meeting-hour (m4a)
gr-rag convert-model               # one-off; or do this in Colab and copy models/ over
gr-rag transcribe                  # SLOW on CPU – see below. Resumable: just re-run.
gr-rag documents                   # download + extract all meeting PDFs (Protokolle, Postulate, ...)
gr-rag status                      # what's done per meeting
gr-rag build-index                 # chunks + embeddings (Ollama must be running)
gr-rag search "Einheitsgemeinde"   # check retrieval scores, tune min_score
gr-rag summarize                   # chapters, cited summaries, vote outcomes (LLM, slow on CPU)
gr-rag add-user anna@duebendorf.ch "Anna Muster"
gr-rag serve                       # http://localhost:8000
```

## Transcription on a 2017 Intel MacBook

It works, but slowly. The model runs on the CPU with `faster-whisper` (int8,
with voice-activity detection that skips silence and breaks). Expect roughly **0.5–2×
realtime**: a 3-hour meeting takes about 2–6 hours, and the full archive takes several days of
running overnight. Progress is saved every 2 minutes, and re-running continues where it stopped.

### UZH ScienceCluster (recommended)

```bash
# on your Mac
scp duebendorf-gr-rag.zip <shortname>@cluster.s3it.uzh.ch:~/
ssh <shortname>@cluster.s3it.uzh.ch
# on the cluster (put it on your larger data storage if $HOME quota is tight)
unzip duebendorf-gr-rag.zip && cd duebendorf-gr-rag
bash cluster/setup.sh                 # env, scrape, audio, model weights (login node, has internet)
sbatch cluster/transcribe.slurm       # GPU job: convert model + transcribe, ~3-5 h
squeue -u $USER; tail -f logs/gr-whisper-*.out
# afterwards, on your Mac:
scp -r <shortname>@cluster.s3it.uzh.ch:~/duebendorf-gr-rag/data/transcripts data/
```

**Otherwise, transcribe on another GPU and run everything else on the Mac.**
`notebooks/transcribe_colab.ipynb` does this on a free Colab T4 (about 20–40× realtime, so the
whole archive takes a few hours). The UZH ScienceCluster works the same way: `pip install -e ".[transcribe,convert]"` and
run `gr-rag convert-model && gr-rag transcribe`. Copy `data/transcripts/` back afterwards.

Intel-Mac caveats:
* `convert-model` needs `torch`. The last torch release with Intel-Mac wheels is 2.2.x,
  so it's easier to convert in Colab and copy `models/whisper-swiss-german-ct2/` to the Mac.
* If `pip install faster-whisper` can't find a `ctranslate2` wheel for your macOS/Python,
  try Python 3.11 or pin `ctranslate2==4.4.0`. Otherwise transcribe in Colab.
* The chatbot itself (Ollama + 3B model) runs fine but answers take maybe 20–60 s on that CPU.

## Notes

* **Model license**: `Flurin17/whisper-large-v3-turbo-swiss-german` is **CC BY-NC 4.0**, so it's
  fine for university research but not for a commercial deployment. The model card also points to
  a newer Nemotron-based fine-tune with better accuracy. You can switch to it in `config.yaml`
  if it's Whisper-compatible.
* Transcripts are machine translations of Swiss German speech. The UI says so on every
  transcript source and links to the video so users can check.
* Speaker names aren't detected (no diarization). The model can only attribute statements
  when the speaker is named in the speech, for example by the council president.
  Adding `pyannote` diarization is a natural next step.
* Scraper is polite (1.5 s between requests, identifying User-Agent).

## Web app (DemocrAI · Ratsarchiv)

Try it right away, with no Ollama, GPU or real data needed:

```bash
pip install -e ".[web]"
gr-rag demo                 # fictional demo meetings, offline stand-in models
# open http://127.0.0.1:8000  ->  demo@example.org / demo1234
```

The demo's "LLM" only copies sentences from the sources, so answers read choppy, but the whole
flow works exactly like production: search, cited answers, summaries, chapters and projects.
All names in the demo are invented.

**Design:** follows the visual language of duebendorf.ch: the open-source **Barlow** font, pure yellow
(`#FFFF00`) breadcrumb bar and active-menu underline, left navigation with grey rules, outlined square buttons,
city-style tables, grey footer, and **Font Awesome 4.7** icons. The font and icons are open-licensed (OFL/MIT) and bundled
locally. The city's coat of arms/logo and photos are deliberately *not* used, and the app says it is not an official
city service. If the city adopts the tool, get its approval and official brand assets before going public.

**Languages (DE / EN):** the switch in the header changes the language of
- the interface (all labels; `frontend/src/i18n-en.ts`),
- AI answers (the model answers in English and still cites [n] after every sentence),
- generated content: summaries, outcomes, chapters, agenda titles and document summaries are machine-translated on demand,
- transcripts and excerpts: "Translate" buttons; the German original stays visible underneath.

Translations reuse the local LLM (`POST /api/translate`), are cached in `data/translations.db`, and are
rejected (German original shown) if a citation marker [n] is lost. German stays authoritative. In the
demo, translation is a crude word glossary because there is no language model.

Pages (from the paper sketches):

| Page | What it does |
|---|---|
| **Home** | SUCHE / FRAGEN (KI) / PLANEN tiles, latest meetings, my projects |
| **Sitzung** | list of meetings, then per meeting: Traktanden (linked documents, search / ask / add to project, *new project from agenda item*), Protokoll (vote outcomes + per-item summary), Zusammenfassung (per-item summary from video, tabs Kapitel / Sprecher), Video & Transkript (YouTube player synced with the transcript), Dokumente (summarize each or all, ask the documents) |
| **Fragen** | chats with streamed, cited answers; filters for source type and dates; save answers or chats to a project |
| **Planen** | projects grouped by category; collected answers, excerpts, agenda items, documents, searches and notes; report editor with "insert with source"; Markdown export |

Available everywhere: search overlay (⌘K); select any text to search the whole archive for it or add it
to a project; the "+ Chat" drawer for a single meeting.

**Accounts:** no self-signup. Create accounts with `gr-rag add-user`. Passwords are stored as scrypt
hashes; sessions are http-only cookies. Each user only sees their own chats and projects. For a public
or shared deployment, put it behind HTTPS (e.g. Caddy or nginx), and consider UZH SSO or shared team
projects as next steps.

**Frontend development:** `uvicorn gr_rag.api:create_app --factory --reload` and
`cd frontend && npm install && npm run dev` (Vite proxies `/api`). `npm run build` writes
`frontend/dist`, which `gr-rag serve` serves. A built copy is included.

## Layout

```
config.yaml               all settings (models, chunk sizes, thresholds)
src/gr_rag/scrape.py      meeting list + detail pages
src/gr_rag/download.py    YouTube audio, Protokoll PDFs → page text
src/gr_rag/transcribe.py  faster-whisper / transformers backends, resumable
src/gr_rag/chunk.py       75 s transcript windows (15 s overlap), Protokoll paragraphs
src/gr_rag/index.py       Ollama embeddings + BM25 hybrid retriever
src/gr_rag/rag.py         prompt, Ollama chat, citation validation
src/gr_rag/summarize.py   chapters (Traktandum alignment), cited summaries, outcomes, doc summaries
src/gr_rag/store.py       SQLite: users, sessions, chats, projects
src/gr_rag/api.py         FastAPI backend
src/gr_rag/demo.py        fictional demo data + offline stand-in models
frontend/                 React + TypeScript (Vite)
notebooks/transcribe_colab.ipynb
tests/                    pytest suite (parsing, chunking, retrieval, grounding)
```
