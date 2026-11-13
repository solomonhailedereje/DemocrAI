"""Load config.yaml and expose project paths."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("GR_RAG_ROOT", Path(__file__).resolve().parents[2]))


@lru_cache(maxsize=1)
def load_config(path: str | os.PathLike | None = None) -> dict:
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass(frozen=True)
class Paths:
    data: Path

    @property
    def meetings(self) -> Path:          # scraped metadata
        return self.data / "meetings.json"

    @property
    def audio(self) -> Path:
        return self.data / "audio"

    @property
    def transcripts(self) -> Path:       # one JSON per meeting, timestamped segments
        return self.data / "transcripts"

    @property
    def pdfs(self) -> Path:
        return self.data / "pdfs"

    @property
    def docs(self) -> Path:              # extracted PDF text per page, one JSON per document
        return self.data / "docs"

    @property
    def index(self) -> Path:
        return self.data / "index"

    @property
    def summaries(self) -> Path:         # generated, cited summaries / chapters / outcomes
        return self.data / "summaries"

    @property
    def db(self) -> Path:                # users, chats, projects
        return self.data / "app.db"

    def ensure(self) -> "Paths":
        for p in (self.data, self.audio, self.transcripts, self.pdfs, self.docs, self.index,
                  self.summaries, self.summaries / "docs"):
            p.mkdir(parents=True, exist_ok=True)
        return self


def paths() -> Paths:
    # GR_RAG_DATA overrides the data folder (tests, or data on a separate disk/server)
    data = os.environ.get("GR_RAG_DATA") or ROOT / load_config()["data_dir"]
    return Paths(Path(data)).ensure()
