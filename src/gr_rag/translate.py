"""Translate German archive content (summaries, transcript lines, excerpts) into English.

Rules that keep translations trustworthy:
  * the German original stays authoritative and is always one click away in the UI;
  * citation markers [n] must survive unchanged - otherwise the translation is
    rejected and the original returned (ok=False), so a citation can never be lost
    or re-pointed by translation;
  * results are cached (SQLite), so each text is translated once.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from collections import Counter
from pathlib import Path

from .rag import CITE_RE, ollama_chat

LANG_NAMES = {"en": "English", "de": "German", "fr": "French", "it": "Italian"}
BATCH = 12
SEP_RE = re.compile(r"^###\s*(\d+)\s*$", re.M)

SYSTEM = """You are a precise translator for a Swiss municipal council archive.
Translate each numbered German text into {lang}.
- Translate faithfully; do not add, explain, summarise or omit anything.
- Keep every citation marker like [1] or [2][3] exactly as it is, in the same place.
- Keep names, party abbreviations, business numbers (e.g. GR Geschäft Nr. 03/2025) and amounts unchanged.
- Swiss terms: Gemeinderat = Municipal Council (parliament), Stadtrat = City Council (executive),
  Traktandum = agenda item, Postulat = postulate, Motion = motion, Interpellation = interpellation.
- Answer ONLY in this format, one block per input, same numbers:
### 1
<translation>
### 2
<translation>"""


def markers_ok(src: str, dst: str) -> bool:
    return Counter(CITE_RE.findall(src)) == Counter(CITE_RE.findall(dst))


def parse_blocks(raw: str, n: int) -> list[str | None]:
    out: list[str | None] = [None] * n
    parts = SEP_RE.split(raw)
    # parts = [pre, num, text, num, text, ...]
    for i in range(1, len(parts) - 1, 2):
        k = int(parts[i]) - 1
        if 0 <= k < n:
            out[k] = parts[i + 1].strip()
    return out


class TranslationCache:
    def __init__(self, path: Path | str):
        self.path = str(path)
        with sqlite3.connect(self.path) as c:
            c.execute("CREATE TABLE IF NOT EXISTS translations (key TEXT PRIMARY KEY, text TEXT NOT NULL)")

    @staticmethod
    def key(text: str, target: str) -> str:
        return hashlib.sha256(f"{target}\x00{text}".encode()).hexdigest()

    def get_many(self, texts: list[str], target: str) -> dict[str, str]:
        keys = {self.key(t, target): t for t in texts}
        if not keys:
            return {}
        with sqlite3.connect(self.path) as c:
            rows = c.execute(f"SELECT key, text FROM translations WHERE key IN ({','.join('?' * len(keys))})",
                             list(keys)).fetchall()
        return {keys[k]: v for k, v in rows}

    def put(self, text: str, target: str, translated: str) -> None:
        with sqlite3.connect(self.path) as c:
            c.execute("INSERT OR REPLACE INTO translations(key, text) VALUES(?, ?)", (self.key(text, target), translated))


def translate_batch(texts: list[str], target: str, chat_fn=None) -> list[str | None]:
    """One LLM call for up to BATCH texts. Returns None where a text could not be translated safely."""
    chat_fn = chat_fn or ollama_chat
    body = "\n".join(f"### {i}\n{t}" for i, t in enumerate(texts, 1))
    raw = "".join(chat_fn([{"role": "system", "content": SYSTEM.format(lang=LANG_NAMES.get(target, target))},
                           {"role": "user", "content": body}]))
    out = parse_blocks(raw, len(texts))
    return [o if o and markers_ok(src, o) else None for src, o in zip(texts, out)]


def translate(texts: list[str], target: str, cache: TranslationCache, chat_fn=None) -> tuple[list[str], list[bool]]:
    """Translate with cache. Returns (texts, ok) - ok=False means the German original was returned."""
    if target == "de":
        return texts, [True] * len(texts)
    cached = cache.get_many(texts, target)
    todo = [t for t in dict.fromkeys(texts) if t.strip() and t not in cached]
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        try:
            results = translate_batch(batch, target, chat_fn)
        except Exception:
            results = [None] * len(batch)
        for src, dst in zip(batch, results):
            if dst is not None:
                cache.put(src, target, dst)
                cached[src] = dst
    out = [cached.get(t, t) for t in texts]
    ok = [(t in cached) or not t.strip() for t in texts]
    return out, ok
