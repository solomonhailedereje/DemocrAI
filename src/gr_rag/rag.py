"""Grounded answering: the LLM may only use retrieved excerpts, and must cite them.

Grounding is enforced in three layers, not just by asking nicely:
  1. Retrieval gate  - if nothing relevant is retrieved, refuse without calling the LLM.
  2. Strict prompt   - answer only from numbered excerpts, cite [n] after every statement.
  3. Post-check      - drop sentences without a valid citation, drop citations to
                       excerpts that don't exist, and refuse if nothing cited survives.
Only the excerpts actually cited are shown as sources, renumbered 1..k.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Iterator

import requests

from .chunk import fmt_ts
from .config import load_config
from .index import Hit, Retriever, tokenize

NO_INFO = ("Dazu finde ich in den Transkripten und Protokollen der Gemeinderatssitzungen "
           "keine Angaben.")
NO_INFO_EN = ("I could not find any information on this in the transcripts and minutes of the "
              "council meetings.")
REFUSALS = {"de": NO_INFO, "en": NO_INFO_EN}
LANG_RULE = {
    "en": ("\n\nANSWER IN ENGLISH. The excerpts are German: translate faithfully, keep names, numbers and "
           "business numbers unchanged, and still cite [n] after every sentence. If the excerpts do not "
           f'answer the question, reply exactly: "{NO_INFO_EN}"'),
}

SYSTEM_PROMPT = f"""Du bist ein Auskunftssystem zu den Sitzungen des Gemeinderats Dübendorf.

REGELN (strikt):
1. Verwende AUSSCHLIESSLICH die nummerierten Auszüge unten. Kein Allgemeinwissen, keine Vermutungen.
2. Setze nach JEDEM Satz die Quelle(n) in eckigen Klammern, z. B. [1] oder [2][4].
3. Wenn die Auszüge die Frage nicht beantworten, antworte genau: "{NO_INFO}"
4. Gib wieder, wer was gesagt hat, wenn es aus dem Auszug hervorgeht. Erfinde keine Namen, Zahlen oder Daten.
5. Transkripte sind automatisch aus Schweizerdeutsch übersetzt und können Fehler enthalten;
   Protokolle sind die offiziellen Sitzungsprotokolle. Bei Widersprüchen nenne beide mit Quelle.
6. Antworte in der Sprache der Frage, knapp und sachlich."""

CITE_RE = re.compile(r"\[(\d+)\]")
SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ\"„(])|\n+")


@dataclass
class Source:
    n: int
    chunk: dict
    support: float = 1.0   # lexical overlap between cited sentences and this excerpt


@dataclass
class Answer:
    text: str
    sources: list[Source] = field(default_factory=list)
    grounded: bool = True
    removed_sentences: list[str] = field(default_factory=list)
    retrieved: list[Hit] = field(default_factory=list)


KIND = {"transcript": "Transkript", "protokoll": "Protokoll", "dokument": "Dokument"}


def format_context(hits: list[Hit]) -> str:
    blocks = []
    for i, h in enumerate(hits, 1):
        c = h.chunk
        kind = KIND.get(c["source_type"], c["source_type"])
        if c["source_type"] == "transcript":
            where = f"Video {fmt_ts(c['start'])}"
        else:
            where = f"{c.get('doc_title', '')}, Seite {c['page']}"
        blocks.append(f"[{i}] {kind} – {c['meeting_title']} vom {c['date']} – {where}\n{c['text']}")
    return "\n\n".join(blocks)


def _messages(question: str, hits: list[Hit], history: list[dict] | None = None,
              lang: str | None = None) -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM_PROMPT + LANG_RULE.get(lang or "", "")}]
    # Earlier turns help resolve follow-ups ("und was sagte die SVP dazu?"),
    # but facts must still come from the excerpts of THIS turn.
    for h in (history or [])[-4:]:
        # strip old [n] markers: they referred to a different excerpt list
        msgs.append({"role": h["role"], "content": CITE_RE.sub("", h["content"])})
    msgs.append({"role": "user", "content": f"AUSZÜGE:\n\n{format_context(hits)}\n\nFRAGE: {question}"})
    return msgs


def generate(task: str, hits: list[Hit], chat_fn=None) -> "Answer":
    """Run a grounded task (summary, outcome list, ...) over given excerpts, validated like answers."""
    if not hits:
        return Answer(NO_INFO, grounded=False)
    chat_fn = chat_fn or ollama_chat
    raw = "".join(chat_fn(_messages(task, hits)))
    return validate(raw, hits)


def ollama_chat(messages: list[dict], stream: bool = True) -> Iterator[str]:
    cfg = load_config()["llm"]
    r = requests.post(f"{load_config()['retrieval']['ollama_url']}/api/chat", stream=stream, timeout=900,
                      json={"model": cfg["model"], "messages": messages, "stream": stream,
                            "options": {"temperature": cfg["temperature"], "num_ctx": cfg["num_ctx"]}})
    r.raise_for_status()
    if not stream:
        yield r.json()["message"]["content"]
        return
    for line in r.iter_lines():
        if line:
            part = json.loads(line)
            yield part.get("message", {}).get("content", "")
            if part.get("done"):
                break


def _overlap(sentence: str, text: str) -> float:
    s = set(tokenize(CITE_RE.sub("", sentence)))
    return len(s & set(tokenize(text))) / len(s) if s else 1.0


def validate(raw: str, hits: list[Hit], lang: str | None = None) -> Answer:
    """Keep only cited sentences that point at real excerpts; renumber sources."""
    raw = raw.strip()
    refusal = REFUSALS.get(lang or "de", NO_INFO)
    if not raw or any(r[:40] in raw for r in REFUSALS.values()):
        return Answer(refusal, grounded=False, retrieved=hits)

    kept, removed, used = [], [], []          # kept: (line_no, sentence, valid_citations)
    for line_no, line in enumerate(l for l in raw.splitlines() if l.strip()):
        for sent in (s.strip() for s in SENT_RE.split(line)):
            if not sent:
                continue
            nums = [int(n) for n in CITE_RE.findall(sent)]
            valid = [n for n in nums if 1 <= n <= len(hits)]
            if not valid:
                removed.append(sent)
                continue
            for n in valid:
                if n not in used:
                    used.append(n)
            kept.append((line_no, sent, valid))

    if not kept:
        return Answer(refusal, grounded=False, removed_sentences=removed, retrieved=hits)

    renum = {old: new for new, old in enumerate(used, 1)}
    support = {n: [] for n in used}
    lines: dict[int, list[str]] = {}
    for line_no, sent, valid in kept:
        for n in valid:
            # word-overlap check only works when answer and excerpt share a language (German)
            support[n].append(_overlap(sent, hits[n - 1].chunk["text"]) if (lang or "de") == "de" else 1.0)
        sent = CITE_RE.sub(lambda m: f"[{renum[int(m.group(1))]}]" if int(m.group(1)) in renum else "", sent)
        lines.setdefault(line_no, []).append(sent)

    sources = [Source(renum[n], hits[n - 1].chunk, round(sum(support[n]) / len(support[n]), 2)) for n in used]
    text = "\n".join(" ".join(s) for _, s in sorted(lines.items()))
    return Answer(text, sources, True, removed, hits)


class RAG:
    def __init__(self, retriever: Retriever | None = None, chat_fn=ollama_chat):
        self.retriever = retriever or Retriever()
        self.chat_fn = chat_fn
        self.min_score = load_config()["retrieval"]["min_score"]

    def retrieve(self, question: str, **filters) -> list[Hit]:
        hits = self.retriever.search(question, **filters)
        if not hits or max(h.dense for h in hits) < self.min_score:
            return []
        return hits

    def stream(self, question: str, history: list[dict] | None = None, lang: str | None = None,
               **filters) -> Iterator[str | Answer]:
        """Yields raw tokens while generating, then a final validated Answer."""
        # For follow-up questions, retrieve with the previous question as extra context
        prev = [h["content"] for h in (history or []) if h["role"] == "user"][-1:]
        hits = self.retrieve(" ".join(prev + [question]), **filters)
        if not hits:
            yield Answer(REFUSALS.get(lang or "de", NO_INFO), grounded=False)
            return
        raw = ""
        for tok in self.chat_fn(_messages(question, hits, history, lang)):
            raw += tok
            yield tok
        yield validate(raw, hits, lang)

    def ask(self, question: str, history: list[dict] | None = None, lang: str | None = None,
            **filters) -> Answer:
        final = None
        for item in self.stream(question, history, lang, **filters):
            if isinstance(item, Answer):
                final = item
        return final
