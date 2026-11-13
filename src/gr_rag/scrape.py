"""Scrape the Dübendorf Gemeinderat meeting list and each meeting's detail page.

The list at /sitzung is rendered client-side from JSON stored in the
`data-entities` attribute of each <table>; we parse that JSON directly.
Each meeting page (/_rte/anlass/<id>) links the YouTube recording,
the documents (Protokoll = file names containing "-PR-") and the agenda.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .config import load_config, paths

DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
TIME_RE = re.compile(r"(\d{1,2})\.(\d{2})\s*Uhr")
DOC_TYPE_RE = re.compile(r"^\d{8}-([A-Z]{2})-")

# Document type codes seen on the site (file-name prefix after the date)
DOC_TYPES = {
    "PR": "Protokoll",
    "TL": "Traktandenliste",
    "PU": "Publikation/Auszug",
    "BS": "Beschluss Stadtrat",
    "PO": "Postulat",
    "MO": "Motion",
    "IP": "Interpellation",
}


@dataclass
class Document:
    title: str
    url: str
    doc_type: str  # two-letter code, e.g. "PR"


@dataclass
class AgendaItem:
    number: str
    title: str
    geschaeft: str = ""
    documents: list[Document] = field(default_factory=list)


@dataclass
class Meeting:
    id: str
    title: str
    url: str
    date: str | None            # ISO date
    start: str | None = None    # "19:00"
    end: str | None = None
    cancelled: bool = False
    youtube_url: str | None = None
    youtube_id: str | None = None
    documents: list[Document] = field(default_factory=list)
    agenda: list[AgendaItem] = field(default_factory=list)

    @property
    def protokolle(self) -> list[Document]:
        return [d for d in self.documents if d.doc_type == "PR"]


# --------------------------------------------------------------------------- helpers

def youtube_id(url: str | None) -> str | None:
    if not url:
        return None
    u = urlparse(url)
    if u.netloc.endswith("youtu.be"):
        return u.path.strip("/").split("/")[0] or None
    if "youtube" in u.netloc:
        if u.path.startswith(("/live/", "/embed/", "/shorts/", "/v/")):
            return u.path.split("/")[2] or None
        return parse_qs(u.query).get("v", [None])[0]
    return None


def youtube_link(video_id: str, seconds: float | None = None) -> str:
    base = f"https://www.youtube.com/watch?v={video_id}"
    return f"{base}&t={int(seconds)}s" if seconds is not None else base


def _parse_date_cell(html: str) -> tuple[str | None, str | None, str | None]:
    text = BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)
    # The cell repeats the date (desktop + mobile variant): keep only the first copy
    dates = list(DATE_RE.finditer(text))
    if len(dates) > 1:
        text = text[: dates[1].start()]
    d = DATE_RE.search(text)
    date = f"{d.group(3)}-{d.group(2)}-{d.group(1)}" if d else None
    times = [f"{int(h):02d}:{m}" for h, m in TIME_RE.findall(text)]
    return date, (times[0] if times else None), (times[1] if len(times) > 1 else None)


def _doc_from_anchor(a, base_url: str) -> Document:
    title = (a.get("title") or a.get_text(" ", strip=True)).strip()
    m = DOC_TYPE_RE.match(title)
    return Document(title=title, url=urljoin(base_url, a["href"]), doc_type=m.group(1) if m else "")


# --------------------------------------------------------------------------- parsing

def parse_meeting_list(html: str, base_url: str) -> list[Meeting]:
    soup = BeautifulSoup(html, "html.parser")
    meetings: dict[str, Meeting] = {}
    for table in soup.select("table[data-entities]"):
        try:
            payload = json.loads(table["data-entities"])
        except (ValueError, KeyError):
            continue
        for row in payload.get("data", []):
            a = BeautifulSoup(row.get("name", ""), "html.parser").find("a", href=True)
            if not a or "/anlass/" not in a["href"]:
                continue
            mid = a["href"].rstrip("/").split("/")[-1]
            title = a.get_text(" ", strip=True)
            date, start, end = _parse_date_cell(row.get("_datum") or row.get("datum") or "")
            meetings[mid] = Meeting(
                id=mid,
                title=title,
                url=urljoin(base_url, a["href"]),
                date=date,
                start=start,
                end=end,
                cancelled="abgesagt" in title.lower(),
            )
    return sorted(meetings.values(), key=lambda m: m.date or "", reverse=True)


def parse_meeting_detail(html: str, meeting: Meeting, base_url: str) -> Meeting:
    soup = BeautifulSoup(html, "html.parser")

    title_el = soup.select_one(".contentTitle")
    if title_el:
        meeting.title = title_el.get_text(" ", strip=True)

    yt = soup.find("a", href=re.compile(r"(youtube\.com|youtu\.be)/"))
    if yt:
        meeting.youtube_url = yt["href"]
        meeting.youtube_id = youtube_id(yt["href"])

    # Agenda: the table whose header contains "Bezeichnung"
    agenda_table = None
    for t in soup.find_all("table"):
        head = t.find("thead")
        if head and "Bezeichnung" in head.get_text():
            agenda_table = t
            break
    agenda_doc_urls: set[str] = set()
    if agenda_table is not None:
        body = agenda_table.find("tbody", recursive=False) or agenda_table
        for tr in body.find_all("tr", recursive=False):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 2:
                continue
            desc = tds[1].find("div", class_="icms-wysiwyg")
            docs = [_doc_from_anchor(a, base_url) for a in tds[1].select('a[href^="/_doc/"]')]
            docs = list({d.url: d for d in docs}.values())
            agenda_doc_urls.update(d.url for d in docs)
            meeting.agenda.append(AgendaItem(
                number=tds[0].get_text(strip=True),
                title=(desc or tds[1]).get_text(" ", strip=True),
                geschaeft=tds[2].get_text(" ", strip=True) if len(tds) > 2 else "",
                documents=docs,
            ))

    # Meeting-level documents (everything else that links to /_doc/)
    seen: dict[str, Document] = {}
    for a in soup.select('a[href^="/_doc/"]'):
        d = _doc_from_anchor(a, base_url)
        if d.url not in agenda_doc_urls and d.url not in seen and d.title.lower() != "download":
            seen[d.url] = d
    meeting.documents = list(seen.values())
    return meeting


# --------------------------------------------------------------------------- driver

def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = load_config()["scrape"]["user_agent"]
    return s


def scrape(only_past: bool = True, since: str | None = None) -> list[Meeting]:
    """The archive goes back to 2004 (~190 meetings); YouTube recordings only
    exist for recent years, older meetings still have Protokolle."""
    cfg = load_config()["scrape"]
    base = cfg["base_url"]
    s = _session()

    html = s.get(urljoin(base, cfg["list_path"]), timeout=30).text
    meetings = parse_meeting_list(html, base)
    today = datetime.now().date().isoformat()
    if only_past:
        meetings = [m for m in meetings if m.date and m.date <= today]
    if since:
        meetings = [m for m in meetings if m.date and m.date >= since]

    for m in meetings:
        if m.cancelled:
            continue
        r = s.get(m.url, timeout=30)
        m.url = r.url
        parse_meeting_detail(r.text, m, base)
        print(f"  {m.date}  {m.title:<35} video={'yes' if m.youtube_id else 'no ':3}  "
              f"protokolle={len(m.protokolle)}  agenda={len(m.agenda)}")
        time.sleep(cfg["delay_seconds"])

    out = paths().meetings
    out.write_text(json.dumps([asdict(m) for m in meetings], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(meetings)} meetings -> {out}")
    return meetings


def load_meetings() -> list[dict]:
    p = paths().meetings
    if not p.exists():
        raise SystemExit("No meetings.json yet - run `gr-rag scrape` first.")
    return json.loads(p.read_text(encoding="utf-8"))
