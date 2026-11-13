import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useOutletContext, useParams } from "react-router-dom";
import type { ShellCtx } from "../components/Layout";
import { type ItemKind, type Project, type ProjectItem, api, fmtDate, fmtTs, sourceHref } from "../api";
import * as I from "../components/Icons";
import { CitedBlock } from "../components/Sources";
import { useApp } from "../context";

const KIND_LABEL: Record<ItemKind, string> = {
  answer: "KI-Antworten", excerpt: "Auszüge", agenda: "Traktanden", document: "Dokumente",
  search: "Suchen", chat: "Chats", meeting: "Sitzungen", note: "Notizen",
};

export default function Planen() {
  const { id } = useParams();
  const pid = id ? Number(id) : null;
  const nav = useNavigate();
  const loc = useLocation();
  const { projects, refreshProjects } = useOutletContext<ShellCtx>();
  const [creating, setCreating] = useState(false);

  useEffect(() => { refreshProjects(); }, [pid, refreshProjects]);
  useEffect(() => { if ((loc.state as any)?.create) setCreating(true); }, [loc.state]);
  useEffect(() => {   // open the most recent project by default
    if (!pid && projects.length && !creating && !(loc.state as any)?.create) {
      const latest = [...projects].sort((a, b) => b.updated.localeCompare(a.updated))[0];
      nav(`/planen/${latest.id}`, { replace: true });
    }
  }, [pid, projects, creating, nav, loc.state]);

  const cats = useMemo(() => [...new Set(projects.map((p) => p.category))], [projects]);

  return (
    <div>
      {creating && (
        <>
          <h1>Neues Projekt</h1>
          <NewProject cats={cats} onDone={(p) => { setCreating(false); refreshProjects(); if (p) nav(`/planen/${p.id}`, { replace: true }); }} />
        </>
      )}
      {!creating && pid && <ProjectView key={pid} pid={pid} cats={cats} onChanged={refreshProjects}
                                        onDeleted={() => { refreshProjects(); nav("/planen", { state: { create: Date.now() } }); }} />}
      {!creating && !pid && projects.length === 0 && <><h1>Planen</h1><Intro /></>}
    </div>
  );
}

function Intro() {
  return (
    <div className="stack">
      <h2>So funktioniert «Planen»</h2>
      <p>Ein Projekt sammelt alles, was Sie für einen Bericht oder ein Geschäft brauchen – geordnet nach Kategorie:</p>
      <ul>
        <li>KI-Antworten mit ihren Quellen (Button «Zu Projekt» im Chat)</li>
        <li>Auszüge aus Videos, Protokollen und Dokumenten</li>
        <li>Traktanden – oder direkt ein neues Projekt aus einem Traktandum mit allen Dokumenten</li>
        <li>gespeicherte Suchen und eigene Notizen</li>
      </ul>
      <p>Rechts schreiben Sie den Bericht und fügen gesammelte Stellen mit Quellenangabe ein. Export als Markdown.</p>
    </div>
  );
}

function NewProject({ cats, onDone }: { cats: string[]; onDone: (p?: Project) => void }) {
  const [title, setTitle] = useState("");
  const [cat, setCat] = useState("");
  return (
    <form className="stack" style={{ marginTop: 16, maxWidth: 520 }}
          onSubmit={async (e) => { e.preventDefault(); if (title.trim()) onDone(await api.createProject(title.trim(), cat.trim() || "Allgemein")); }}>
      <input className="input" autoFocus placeholder="Titel" value={title} onChange={(e) => setTitle(e.target.value)} />
      <input className="input" list="pcats" placeholder="Kategorie (z. B. Bildung)" value={cat} onChange={(e) => setCat(e.target.value)} />
      <datalist id="pcats">{cats.map((c) => <option key={c} value={c} />)}</datalist>
      <div className="row"><button className="btn primary" disabled={!title.trim()}>Erstellen</button>
        <button type="button" className="btn" onClick={() => onDone()}>Abbrechen</button></div>
    </form>
  );
}

function ProjectView({ pid, cats, onChanged, onDeleted }: { pid: number; cats: string[]; onChanged: () => void; onDeleted: () => void }) {
  const { toast, setCrumbTitle } = useApp();
  const [p, setP] = useState<Project | null>(null);
  const [report, setReport] = useState("");
  const [saved, setSaved] = useState<"saved" | "saving" | "dirty">("saved");
  const [kindFilter, setKindFilter] = useState<ItemKind | "all">("all");
  const [noteText, setNoteText] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);
  const timer = useRef<number>();

  useEffect(() => { api.project(pid).then((x) => { setP(x); setReport(x.report); }); }, [pid]);
  useEffect(() => { if (p) setCrumbTitle(p.title); }, [p?.title, setCrumbTitle]);

  const patch = async (fields: Partial<Project>) => { const x = await api.updateProject(pid, fields); setP(x); onChanged(); };

  const onReport = (v: string) => {
    setReport(v); setSaved("dirty");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => { setSaved("saving"); await api.updateProject(pid, { report: v }); setSaved("saved"); }, 800);
  };

  const insert = (snippet: string) => {
    const el = area.current;
    const pos = el ? el.selectionStart : report.length;
    const v = report.slice(0, pos) + (pos && report[pos - 1] !== "\n" ? "\n\n" : "") + snippet + "\n\n" + report.slice(pos);
    onReport(v);
    toast("In den Bericht eingefügt");
  };

  const removeItem = async (it: ProjectItem) => {
    await api.deleteItem(pid, it.id);
    setP((x) => x && { ...x, items: x.items!.filter((i) => i.id !== it.id) });
    onChanged();
  };

  const addNote = async () => {
    if (!noteText.trim()) return;
    const it = await api.addItem(pid, { kind: "note", title: noteText.trim().slice(0, 80), ref: { text: noteText.trim() } });
    setP((x) => x && { ...x, items: [...x.items!, it] });
    setNoteText(""); onChanged();
  };

  async function exportMd() {
    const md = await api.exportProject(pid);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
    a.download = `${p!.title.replace(/[^\wäöüÄÖÜ -]+/g, "").trim() || "bericht"}.md`;
    a.click();
  }

  if (!p) return <div className="muted">Lade Projekt …</div>;
  const items = p.items ?? [];
  const kinds = [...new Set(items.map((i) => i.kind))];
  const shown = items.filter((i) => kindFilter === "all" || i.kind === kindFilter);

  return (
    <div>
      <div className="row" style={{ alignItems: "flex-start" }}>
        <div style={{ flex: 1 }}>
          <input className="title-input" defaultValue={p.title} onBlur={(e) => e.target.value.trim() && e.target.value !== p.title && patch({ title: e.target.value.trim() })} />
          <div className="row small" style={{ marginTop: ".3rem" }}>
            <span className="muted">Kategorie</span>
            <input className="input" list="pcats2" style={{ width: 180, padding: ".2rem .5rem" }} defaultValue={p.category}
                   onBlur={(e) => e.target.value.trim() && e.target.value !== p.category && patch({ category: e.target.value.trim() })} />
            <datalist id="pcats2">{cats.map((c) => <option key={c} value={c} />)}</datalist>
            <span className="muted">· aktualisiert {fmtDate(p.updated)}</span>
          </div>
        </div>
        <button className="btn" onClick={exportMd}><I.Download /> Export</button>
        <button className="btn" title="Projekt löschen"
                onClick={async () => { if (confirm(`Projekt «${p.title}» löschen?`)) { await api.deleteProject(pid); onDeleted(); } }}><I.Trash /></button>
      </div>
      <textarea className="textarea" style={{ marginTop: ".75rem", minHeight: "2.6rem" }} placeholder="Beschreibung / Auftrag (optional)"
                defaultValue={p.description} onBlur={(e) => e.target.value !== p.description && patch({ description: e.target.value })} />

      <div className="project-grid" style={{ marginTop: "1.25rem" }}>
        <section>
          <div className="section-head"><h2>Sammlung</h2><span className="muted small">{items.length} Einträge</span></div>
          <div className="row wrap" style={{ marginBottom: ".75rem" }}>
            <button className={`btn small ${kindFilter === "all" ? "primary" : ""}`} onClick={() => setKindFilter("all")}>Alle</button>
            {kinds.map((k) => (
              <button key={k} className={`btn small ${kindFilter === k ? "primary" : ""}`} onClick={() => setKindFilter(k)}>
                {KIND_LABEL[k]} ({items.filter((i) => i.kind === k).length})</button>
            ))}
          </div>
          {items.length === 0 && <div className="empty">Noch leer. Nutzen Sie «+ Projekt» bei Antworten, Traktanden, Dokumenten oder Suchergebnissen.</div>}
          {shown.map((it) => <ItemCard key={it.id} it={it} pid={pid} onInsert={insert} onRemove={() => removeItem(it)} />)}
          <div className="panel" style={{ marginTop: 16 }}>
            <div className="item-kind">Neue Notiz</div>
            <textarea className="textarea" style={{ minHeight: "3rem", marginTop: ".3rem" }} value={noteText} onChange={(e) => setNoteText(e.target.value)} placeholder="Gedanke, Aufgabe, offene Frage …" />
            <button className="btn small" style={{ marginTop: ".4rem" }} disabled={!noteText.trim()} onClick={addNote}><I.Plus /> Notiz hinzufügen</button>
          </div>
        </section>

        <section className="report">
          <div className="section-head"><h2>Bericht</h2>
            <span className="muted small">{{ saved: "gespeichert", saving: "speichert …", dirty: "…" }[saved]}</span></div>
          <textarea ref={area} className="textarea" value={report} onChange={(e) => onReport(e.target.value)}
                    placeholder={"Schreiben Sie hier Ihren Bericht (Markdown).\n\nMit «In Bericht» fügen Sie gesammelte Stellen samt Quellenangabe an der Cursorposition ein."} />
          <p className="muted small">Tipp: KI-Antworten im Bericht immer mit den angegebenen Quellen prüfen.</p>
        </section>
      </div>
    </div>
  );
}

function ItemCard({ it, pid, onInsert, onRemove }: { it: ProjectItem; pid: number; onInsert: (s: string) => void; onRemove: () => void }) {
  const { openSearch } = useApp();
  const r = it.ref;
  const [note, setNote] = useState(it.note);

  let body: React.ReactNode = null;
  let link: React.ReactNode = null;
  switch (it.kind) {
    case "answer":
      body = r.text ? <CitedBlock text={r.text} sources={r.sources ?? []} compact /> : null;
      if (r.chat_id) link = <Link to={`/fragen/${r.chat_id}`} className="small">Chat öffnen</Link>;
      break;
    case "excerpt":
      body = <div className="source-text clamp" data-selectable>{r.text}</div>;
      link = r.source_type === "transcript" && r.meeting_id
        ? <Link className="small" to={sourceHref(r as any)}><I.Play /> Video {fmtTs(r.start ?? 0)}</Link>
        : r.url && <a className="small" href={r.url} target="_blank" rel="noreferrer"><I.External /> PDF S. {r.page}</a>;
      break;
    case "agenda":
    case "meeting":
      link = r.meeting_id && <Link className="small" to={`/sitzungen/${r.meeting_id}`}>{r.meeting_title} · {fmtDate(r.date)}</Link>;
      break;
    case "document":
      link = <span className="row small">{r.url && <a href={r.url} target="_blank" rel="noreferrer"><I.External /> PDF</a>}
        {r.meeting_id && <Link to={`/sitzungen/${r.meeting_id}#documents`}>Sitzung</Link>}</span>;
      break;
    case "search":
      body = r.top?.length ? <div className="muted small">{r.top.length} Top-Treffer gespeichert: {r.top.map((t: any) => `${t.meeting_title} (${t.label})`).slice(0, 3).join("; ")}</div> : null;
      link = <button className="btn small" onClick={() => openSearch(r.query)}><I.Search /> Erneut suchen</button>;
      break;
    case "chat":
      link = <Link className="small" to={`/fragen/${r.chat_id}`}>Chat öffnen</Link>;
      break;
    case "note":
      body = <div style={{ whiteSpace: "pre-wrap" }} data-selectable>{r.text}</div>;
      break;
  }

  return (
    <div className="item-card">
      <div className="row">
        <span className="item-kind">{KIND_LABEL[it.kind].replace(/en$|e$/, "")}</span>
        <span className="spacer" />
        <button className="btn small" title="An Cursorposition in den Bericht einfügen" onClick={() => onInsert(snippet(it, note))}><I.Insert /> In Bericht</button>
        <button className="btn small ghost" title="Entfernen" onClick={onRemove}><I.Trash /></button>
      </div>
      {it.kind !== "note" && <div className="item-title">{it.title}</div>}
      {body}
      <div className="row" style={{ marginTop: ".3rem" }}>{link}</div>
      <input className="input small" style={{ marginTop: ".4rem", padding: ".25rem .5rem" }} placeholder="Notiz …" value={note}
             onChange={(e) => setNote(e.target.value)} onBlur={() => note !== it.note && api.updateItem(pid, it.id, note)} />
    </div>
  );
}

/** Markdown snippet for the report, always with a source reference. */
function snippet(it: ProjectItem, note: string): string {
  const r = it.ref;
  const src = (s: any) => s.source_type === "transcript"
    ? `${s.meeting_title}, ${fmtDate(s.date)}, Video ${fmtTs(s.start ?? 0)}${s.url ? ` (${s.url})` : ""}`
    : `${s.doc_title ?? s.meeting_title}, S. ${s.page}${s.url ? ` (${s.url})` : ""}`;
  let out = "";
  switch (it.kind) {
    case "answer":
      out = `${r.question ? `**${r.question}**\n\n` : ""}${r.text}\n\n` +
        (r.sources ?? []).map((s: any) => `[${s.n}] ${src(s)}`).join("  \n");
      break;
    case "excerpt": out = `> «${r.text}»\n\n— ${src(r)}`; break;
    case "agenda": out = `**${it.title}** (${r.meeting_title}, ${fmtDate(r.date)})`; break;
    case "meeting": out = `**${it.title}**`; break;
    case "document": out = `[${it.title}](${r.url})`; break;
    case "search": out = `Suche «${r.query}»: ` + (r.top ?? []).slice(0, 5).map((t: any) => src(t)).join("; "); break;
    case "chat": out = `Siehe Chat «${it.title}»`; break;
    case "note": out = r.text; break;
  }
  return note ? `${out}\n\n_Notiz: ${note}_` : out;
}
