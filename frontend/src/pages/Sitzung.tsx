import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { type Chapter, type Doc, type DocSummary, type Meeting, type Segment, DOC_TYPES, api, fmtDate, fmtTs } from "../api";
import * as I from "../components/Icons";
import { CitedBlock, citedToProps } from "../components/Sources";
import VideoTranscript, { type VideoHandle } from "../components/VideoTranscript";
import { useApp } from "../context";

const SECTIONS = [
  ["agenda", "Traktanden"], ["protokoll", "Protokoll"], ["summary", "Zusammenfassung"],
  ["video", "Video und Transkript"], ["documents", "Dokumente"],
] as const;

export default function Sitzung() {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const startAt = params.get("t") ? Number(params.get("t")) : undefined;
  const { openChat, openSearch, addToProject, toast, setCrumbTitle } = useApp();
  const nav = useNavigate();
  const [m, setM] = useState<Meeting | null>(null);
  const [segments, setSegments] = useState<Segment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const video = useRef<VideoHandle>(null);

  useEffect(() => {
    setM(null); setSegments(null); setError(null);
    api.meeting(id).then(setM).catch((e) => setError(e.message));
    api.transcript(id).then((t) => setSegments(t.segments)).catch(() => setSegments(null));
  }, [id]);

  useEffect(() => {
    if (m && startAt !== undefined) {
      setTimeout(() => document.getElementById("video")?.scrollIntoView({ behavior: "smooth" }), 150);
    }
  }, [m, startAt]);

  useEffect(() => { if (m) setCrumbTitle(m.title); }, [m, setCrumbTitle]);

  if (error) return <div className="notice error">{error}</div>;
  if (!m) return <div className="muted">Lade Sitzung …</div>;

  const chapters = m.summary?.chapters ?? [];
  const chapterOf = (num: string) => chapters.find((c) => c.number === num);
  const seek = (t: number) => {
    document.getElementById("video")?.scrollIntoView({ behavior: "smooth", block: "start" });
    video.current?.seek(t);
  };
  const meetingRef = { meeting_id: m.id, meeting_title: m.title, date: m.date };

  async function projectFromItem(number: string) {
    const p = await api.projectFromAgenda(m!.id, number);
    toast(`Projekt «${p.title}» erstellt`, { to: `/planen/${p.id}`, label: "Öffnen" });
  }

  return (
    <div className="page-narrow">
      <div className="meeting-head">
        <h1 style={{ flex: 1, minWidth: 300 }}>{m.title}</h1>
        <button className="btn" onClick={() => addToProject({ kind: "meeting", title: `${m.title} (${fmtDate(m.date)})`, ref: meetingRef })}>
          <I.Plus /> Projekt
        </button>
        <button className="btn yellow" onClick={() => openChat({ meetingId: m.id, meetingTitle: m.title })}>
          <I.Sparkle /> + Chat
        </button>
      </div>
      <div className="meta" style={{ marginTop: 12 }}>
        {fmtDateLong(m.date)}{m.start ? `, ${m.start.replace(":", ".")} Uhr` : ""}{m.end ? ` – ${m.end.replace(":", ".")} Uhr` : ""}
      </div>

      <h2 style={{ marginTop: 32 }}>Informationen</h2>
      <dl className="info-dl">
        <dt>Video</dt>
        <dd>{m.youtube_id
          ? <a href="#video">Video mit Transkript ansehen</a>
          : <span className="muted">kein Video verfügbar</span>}</dd>
        <dt>Ort</dt><dd>Obere Mühle, Oberdorfstrasse 15</dd>
        <dt>Originalseite</dt>
        <dd><a href={m.url} target="_blank" rel="noreferrer">Sitzung auf duebendorf.ch</a> <I.External /></dd>
      </dl>
      <nav className="anchors" aria-label="Abschnitte">
        {SECTIONS.map(([key, label]) => <a key={key} href={`#${key}`}>{label}</a>)}
      </nav>

      {/* ---------------------------------------------------------------- AGENDA */}
      <Section id="agenda" title="Traktanden">
        {m.agenda.length === 0 ? <div className="empty">Keine Traktandenliste verfügbar.</div> : (
          <table className="dt">
            <thead><tr><th style={{ width: "3rem" }}>Nr.</th><th>Bezeichnung</th><th style={{ width: "6rem" }}>Geschäft</th></tr></thead>
            <tbody>
              {m.agenda.map((a) => {
                const ch = chapterOf(a.number);
                return (
                  <tr key={a.number}>
                    <td>{a.number}</td>
                    <td>
                      <div data-selectable>{a.title}</div>
                      {a.documents.length > 0 && (
                        <div className="doc-links">
                          {a.documents.map((d) => (
                            <a key={d.url} className="doc-link" href={d.url} target="_blank" rel="noreferrer" title={d.title}>
                              <I.Doc /> {stripPrefix(d.title)} <span className="muted">({DOC_TYPES[d.doc_type] ?? "PDF"})</span>
                            </a>
                          ))}
                        </div>
                      )}
                      <div className="agenda-actions" style={{ justifyContent: "flex-start", marginTop: 10 }}>
                        {ch && <button className="btn small" onClick={() => seek(ch.start)}><I.Play /> Video {fmtTs(ch.start)}</button>}
                        <button className="btn small" title="Alle Erwähnungen im Archiv" onClick={() => openSearch(a.title.split(" / ")[0])}><I.Search /> Suchen</button>
                        <button className="btn small" onClick={() => openChat({ meetingId: m.id, meetingTitle: m.title, question: `Was wurde zu Traktandum ${a.number} («${a.title}») besprochen und beschlossen?` })}>
                          <I.Sparkle /> Fragen</button>
                        <button className="btn small" onClick={() => addToProject({ kind: "agenda", title: `Traktandum ${a.number}: ${a.title}`, ref: { ...meetingRef, number: a.number } })}>
                          <I.Plus /> Projekt</button>
                        <button className="btn small" title="Neues Projekt mit Traktandum und Dokumenten" onClick={() => projectFromItem(a.number)}>
                          <I.Folder /> Neues Projekt</button>
                      </div>
                    </td>
                    <td>{a.geschaeft}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Section>

      {/* ---------------------------------------------------------------- PROTOKOLL */}
      <Section id="protokoll" title="Protokoll">
        {!m.has_protokoll && <div className="empty">Für diese Sitzung ist (noch) kein Protokoll publiziert.</div>}
        {m.has_protokoll && !m.summary && <NoSummary />}
        {m.summary && (
          <>
            <h3>Ergebnisse und Abstimmungen</h3>
            {m.summary.outcomes.length === 0 && <p className="muted small">Keine Abstimmungsresultate erkannt.</p>}
            {m.summary.outcomes.map((o, i) => <div key={i} className="summary-item"><CitedBlock {...citedToProps(o)} compact /></div>)}
            <h3 style={{ marginTop: 28 }}>Zusammenfassung nach Traktandum</h3>
            {m.summary.items.filter((it) => it.protokoll).map((it) => (
              <div key={it.number} className="summary-item">
                <div className="item-title">{it.number}. {it.title}</div>
                <CitedBlock {...citedToProps(it.protokoll!)} compact />
              </div>
            ))}
          </>
        )}
        {m.documents.filter((d) => d.doc_type === "PR").map((d) => (
          <p key={d.url} className="small"><a className="doc-link" href={d.url} target="_blank" rel="noreferrer"><I.Doc /> {stripPrefix(d.title)}</a></p>
        ))}
      </Section>

      {/* ---------------------------------------------------------------- SUMMARY (video) */}
      <Section id="summary" title="Zusammenfassung">
        {!m.has_transcript && <div className="empty">{m.has_video ? "Video noch nicht transkribiert." : "Kein Video für diese Sitzung."}</div>}
        {m.has_transcript && !m.summary && <NoSummary />}
        {m.summary && <VideoSummary m={m} chapters={chapters} seek={seek} />}
      </Section>

      {/* ---------------------------------------------------------------- VIDEO */}
      <Section id="video" title="Video und Transkript">
        <VideoTranscript ref={video} videoId={m.youtube_id} segments={segments} chapters={chapters}
                         meetingId={m.id} meetingTitle={m.title} date={m.date} startAt={startAt} />
      </Section>

      {/* ---------------------------------------------------------------- DOCUMENTS */}
      <Section id="documents" title="Dokumente">
        <Documents m={m} onAsk={(q) => openChat({ meetingId: m.id, meetingTitle: m.title, question: q, sourceTypes: ["protokoll", "dokument"] })} />
      </Section>

      <div className="share">
        <button onClick={() => window.print()}><I.Print /> Drucken</button>
        <button onClick={() => { navigator.clipboard?.writeText(location.href); toast("Link kopiert"); }}><I.External /> Link kopieren</button>
        <button onClick={() => nav("/sitzungen")}><I.AngleRight /> Alle Sitzungen</button>
      </div>
    </div>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(true);
  return (
    <section id={id} className={`section ${open ? "" : "closed"}`}>
      <div className="section-head">
        <h2>{title}</h2>
        <button className="collapse" onClick={() => setOpen(!open)} aria-label={open ? "Zuklappen" : "Aufklappen"}><I.AngleDown /></button>
      </div>
      <div className="section-body">{children}</div>
    </section>
  );
}

function NoSummary() {
  return <div className="notice">Die KI-Übersicht wurde für diese Sitzung noch nicht erstellt (<code>gr-rag summarize</code>).</div>;
}

function VideoSummary({ m, chapters, seek }: { m: Meeting; chapters: Chapter[]; seek: (t: number) => void }) {
  const [tab, setTab] = useState<"chapters" | "speakers">("chapters");
  const items = m.summary!.items.filter((it) => it.video);
  return (
    <>
      {items.length === 0 && <div className="muted small">Keine Zusammenfassung aus dem Video verfügbar.</div>}
      {items.map((it) => (
        <div key={it.number} className="summary-item">
          <div className="row item-title">
            {it.number}. {it.title}
            {chapters.find((c) => c.number === it.number) && (
              <button className="btn small ghost" title="Im Video abspielen" onClick={() => seek(chapters.find((c) => c.number === it.number)!.start)}><I.Play /></button>
            )}
          </div>
          <CitedBlock {...citedToProps(it.video!)} compact onSeek={seek} />
        </div>
      ))}

      <div style={{ marginTop: 28 }}>
        <div className="tabs">
          <button className={tab === "chapters" ? "on" : ""} onClick={() => setTab("chapters")}>Kapitel</button>
          <button className={tab === "speakers" ? "on" : ""} onClick={() => setTab("speakers")}>Sprecher</button>
        </div>
        {tab === "chapters" && (
          chapters.length === 0 ? <div className="muted small">Keine Kapitel erkannt.</div> : chapters.map((c) => (
            <div key={c.number} className="chapter" onClick={() => seek(c.start)}>
              <span className="ts">{fmtTs(c.start)}</span>
              <span>{c.number}. {c.title}</span>
              <span className={`chip ${c.confidence === "announced" ? "green" : "grey"}`}
                    title={c.confidence === "announced" ? "Im Video angekündigt («Traktandum …»)" : "Geschätzt aus dem Inhalt"}>
                {c.confidence === "announced" ? "angekündigt" : "geschätzt"}
              </span>
            </div>
          ))
        )}
        {tab === "speakers" && (
          <div className="empty">
            Sprechererkennung folgt in einer nächsten Version. Bis dahin werden Namen nur genannt, wenn sie im Video
            ausgesprochen werden (z. B. «Das Wort hat …»).
          </div>
        )}
      </div>
    </>
  );
}

function Documents({ m, onAsk }: { m: Meeting; onAsk: (q: string) => void }) {
  const { addToProject } = useApp();
  const [sums, setSums] = useState<Record<string, DocSummary | "loading" | string>>({});
  const [q, setQ] = useState("");
  const docs = m.documents;

  useEffect(() => {   // load existing (cached) summaries
    docs.filter((d) => d.has_summary).forEach((d) =>
      api.docSummary(d.doc_id).then((s) => setSums((x) => ({ ...x, [d.doc_id]: s }))).catch(() => {}));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [m.id]);

  async function summarize(d: Doc, refresh = false) {
    setSums((x) => ({ ...x, [d.doc_id]: "loading" }));
    try {
      const s = await api.makeDocSummary(d.doc_id, refresh);
      setSums((x) => ({ ...x, [d.doc_id]: s }));
    } catch (e: any) {
      setSums((x) => ({ ...x, [d.doc_id]: `Fehler: ${e.message}` }));
    }
  }
  async function summarizeAll() {
    for (const d of docs) if (d.has_text && typeof sums[d.doc_id] !== "object") await summarize(d);
  }
  const done = docs.filter((d) => typeof sums[d.doc_id] === "object").length;

  return (
    <>
      <div className="panel" style={{ marginBottom: 24 }}>
        <div className="row"><h3>Überblick</h3><span className="spacer" />
          <button className="btn small" disabled={!docs.some((d) => d.has_text)} onClick={summarizeAll}><I.Sparkle /> Alle zusammenfassen</button></div>
        <p className="small" style={{ margin: "4px 0 12px" }}>
          {docs.length} Dokumente · {done} zusammengefasst. Zusammenfassungen zeigen, was wichtig ist – mit Seitenangabe.
        </p>
        <form className="row" onSubmit={(e) => { e.preventDefault(); if (q.trim()) { onAsk(q); setQ(""); } }}>
          <span className="chip yellow"><I.Sparkle /> Fragen (KI)</span>
          <input className="input" placeholder="Frage zu den Dokumenten dieser Sitzung …" value={q} onChange={(e) => setQ(e.target.value)} />
          <button className="btn primary" disabled={!q.trim()}>Fragen</button>
        </form>
      </div>

      <table className="dt">
        <thead><tr><th>Name</th><th style={{ width: "13rem", textAlign: "right" }}>Aktionen</th></tr></thead>
        <tbody>
          {docs.length === 0 && <tr><td colSpan={2} className="muted">Keine Dokumente.</td></tr>}
          {docs.map((d) => {
            const s = sums[d.doc_id];
            return (
              <tr key={d.url}>
                <td>
                  <a className="title" href={d.url} target="_blank" rel="noreferrer">{d.title}</a>{" "}
                  <span className="muted">({DOC_TYPES[d.doc_type] ?? "PDF"}{d.n_pages ? `, ${d.n_pages} S.` : ""}{d.agenda ? `, Traktandum ${d.agenda}` : ""})</span>
                  {!d.has_text && <div className="muted small">Text noch nicht extrahiert (gr-rag documents)</div>}
                  {s === "loading" && <div className="typing small">Fasse zusammen </div>}
                  {typeof s === "string" && s !== "loading" && <div className="notice error small">{s}</div>}
                  {typeof s === "object" && (
                    <div style={{ marginTop: 8 }}>
                      {s.blocks.length === 0 && <div className="muted small">Keine belegbare Zusammenfassung möglich.</div>}
                      {s.blocks.map((b, i) => <CitedBlock key={i} {...citedToProps(b)} compact />)}
                      {s.pages_covered < s.pages_total && <div className="muted small">Zusammenfassung der ersten {s.pages_covered} von {s.pages_total} Seiten.</div>}
                    </div>
                  )}
                </td>
                <td>
                  <div className="agenda-actions">
                    <a className="btn small" href={d.url} target="_blank" rel="noreferrer">Download</a>
                    <button className="btn small" disabled={!d.has_text || s === "loading"} onClick={() => summarize(d, typeof s === "object")}>
                      <I.Sparkle /> {typeof s === "object" ? "Neu" : "Zusammenfassen"}</button>
                    <button className="btn small" onClick={() => addToProject({ kind: "document", title: d.title, ref: { doc_id: d.doc_id, url: d.url, meeting_id: m.id, doc_type: d.doc_type } })}>
                      <I.Plus /> Projekt</button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}

const MONTHS = ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sept.", "Okt.", "Nov.", "Dez."];
const fmtDateLong = (iso: string | null) => {
  if (!iso) return "";
  const [y, mo, d] = iso.split("-").map(Number);
  return `${d}. ${MONTHS[mo - 1]} ${y}`;
};

const stripPrefix = (t: string) => t.replace(/^\d{8}-[A-Z]{2}-(\d+-)?/, "");
