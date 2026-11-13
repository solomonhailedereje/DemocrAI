import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useOutletContext, useParams } from "react-router-dom";
import type { ShellCtx } from "../components/Layout";
import { type ItemKind, type Project, type ProjectItem, api, fmtDate, fmtTs, sourceHref } from "../api";
import * as I from "../components/Icons";
import { CitedBlock } from "../components/Sources";
import { useApp } from "../context";
import { useT } from "../i18n";

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
  const t = useT();

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
          <h1>{t("Neues Projekt")}</h1>
          <NewProject cats={cats} onDone={(p) => { setCreating(false); refreshProjects(); if (p) nav(`/planen/${p.id}`, { replace: true }); }} />
        </>
      )}
      {!creating && pid && <ProjectView key={pid} pid={pid} cats={cats} onChanged={refreshProjects}
                                        onDeleted={() => { refreshProjects(); nav("/planen", { state: { create: Date.now() } }); }} />}
      {!creating && !pid && projects.length === 0 && <><h1>{t("Planen")}</h1><Intro /></>}
    </div>
  );
}

function Intro() {
  const t = useT();
  return (
    <div className="stack">
      <h2>{t("So funktioniert «Planen»")}</h2>
      <p>{t("Ein Projekt sammelt alles, was Sie für einen Bericht oder ein Geschäft brauchen – geordnet nach Kategorie:")}</p>
      <ul>
        <li>{t("KI-Antworten mit ihren Quellen (Button «Zu Projekt» im Chat)")}</li>
        <li>{t("Auszüge aus Videos, Protokollen und Dokumenten")}</li>
        <li>{t("Traktanden – oder direkt ein neues Projekt aus einem Traktandum mit allen Dokumenten")}</li>
        <li>{t("gespeicherte Suchen und eigene Notizen")}</li>
      </ul>
      <p>{t("Rechts schreiben Sie den Bericht und fügen gesammelte Stellen mit Quellenangabe ein. Export als Markdown.")}</p>
    </div>
  );
}

function NewProject({ cats, onDone }: { cats: string[]; onDone: (p?: Project) => void }) {
  const t = useT();
  const [title, setTitle] = useState("");
  const [cat, setCat] = useState("");
  return (
    <form className="stack" style={{ marginTop: 16, maxWidth: 520 }}
          onSubmit={async (e) => { e.preventDefault(); if (title.trim()) onDone(await api.createProject(title.trim(), cat.trim() || "Allgemein")); }}>
      <input className="input" autoFocus placeholder={t("Titel")} value={title} onChange={(e) => setTitle(e.target.value)} />
      <input className="input" list="pcats" placeholder={t("Kategorie (z. B. Bildung)")} value={cat} onChange={(e) => setCat(e.target.value)} />
      <datalist id="pcats">{cats.map((c) => <option key={c} value={c} />)}</datalist>
      <div className="row"><button className="btn primary" disabled={!title.trim()}>{t("Erstellen")}</button>
        <button type="button" className="btn" onClick={() => onDone()}>{t("Abbrechen")}</button></div>
    </form>
  );
}

function ProjectView({ pid, cats, onChanged, onDeleted }: { pid: number; cats: string[]; onChanged: () => void; onDeleted: () => void }) {
  const { toast, setCrumbTitle } = useApp();
  const t = useT();
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
    toast(t("In den Bericht eingefügt"));
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

  if (!p) return <div className="muted">{t("Lade Projekt …")}</div>;
  const items = p.items ?? [];
  const kinds = [...new Set(items.map((i) => i.kind))];
  const shown = items.filter((i) => kindFilter === "all" || i.kind === kindFilter);

  return (
    <div>
      <div className="row" style={{ alignItems: "flex-start" }}>
        <div style={{ flex: 1 }}>
          <input className="title-input" defaultValue={p.title} onBlur={(e) => e.target.value.trim() && e.target.value !== p.title && patch({ title: e.target.value.trim() })} />
          <div className="row small" style={{ marginTop: ".3rem" }}>
            <span className="muted">{t("Kategorie")}</span>
            <input className="input" list="pcats2" style={{ width: 180, padding: ".2rem .5rem" }} defaultValue={p.category}
                   onBlur={(e) => e.target.value.trim() && e.target.value !== p.category && patch({ category: e.target.value.trim() })} />
            <datalist id="pcats2">{cats.map((c) => <option key={c} value={c} />)}</datalist>
            <span className="muted">· {t("aktualisiert")} {fmtDate(p.updated)}</span>
          </div>
        </div>
        <button className="btn" onClick={exportMd}><I.Download /> {t("Export")}</button>
        <button className="btn" title={t("Projekt löschen")}
                onClick={async () => { if (confirm(t("Projekt «{p}» löschen?", { p: p.title }))) { await api.deleteProject(pid); onDeleted(); } }}><I.Trash /></button>
      </div>
      <textarea className="textarea" style={{ marginTop: ".75rem", minHeight: "2.6rem" }} placeholder={t("Beschreibung / Auftrag (optional)")}
                defaultValue={p.description} onBlur={(e) => e.target.value !== p.description && patch({ description: e.target.value })} />

      <div className="project-grid" style={{ marginTop: "1.25rem" }}>
        <section>
          <div className="section-head"><h2>{t("Sammlung")}</h2><span className="muted small">{t("{n} Einträge", { n: items.length })}</span></div>
          <div className="row wrap" style={{ marginBottom: ".75rem" }}>
            <button className={`btn small ${kindFilter === "all" ? "primary" : ""}`} onClick={() => setKindFilter("all")}>{t("Alle")}</button>
            {kinds.map((k) => (
              <button key={k} className={`btn small ${kindFilter === k ? "primary" : ""}`} onClick={() => setKindFilter(k)}>
                {t(KIND_LABEL[k])} ({items.filter((i) => i.kind === k).length})</button>
            ))}
          </div>
          {items.length === 0 && <div className="empty">{t("Noch leer. Nutzen Sie «+ Projekt» bei Antworten, Traktanden, Dokumenten oder Suchergebnissen.")}</div>}
          {shown.map((it) => <ItemCard key={it.id} it={it} pid={pid} onInsert={insert} onRemove={() => removeItem(it)} />)}
          <div className="panel" style={{ marginTop: 16 }}>
            <div className="item-kind">{t("Neue Notiz")}</div>
            <textarea className="textarea" style={{ minHeight: "3rem", marginTop: ".3rem" }} value={noteText} onChange={(e) => setNoteText(e.target.value)} placeholder={t("Gedanke, Aufgabe, offene Frage …")} />
            <button className="btn small" style={{ marginTop: ".4rem" }} disabled={!noteText.trim()} onClick={addNote}><I.Plus /> {t("Notiz hinzufügen")}</button>
          </div>
        </section>

        <section className="report">
          <div className="section-head"><h2>{t("Bericht")}</h2>
            <span className="muted small">{{ saved: t("gespeichert"), saving: t("speichert …"), dirty: "…" }[saved]}</span></div>
          <textarea ref={area} className="textarea" value={report} onChange={(e) => onReport(e.target.value)}
                    placeholder={t("Schreiben Sie hier Ihren Bericht (Markdown).\n\nMit «In Bericht» fügen Sie gesammelte Stellen samt Quellenangabe an der Cursorposition ein.")} />
          <p className="muted small">{t("Tipp: KI-Antworten im Bericht immer mit den angegebenen Quellen prüfen.")}</p>
        </section>
      </div>
    </div>
  );
}

function ItemCard({ it, pid, onInsert, onRemove }: { it: ProjectItem; pid: number; onInsert: (s: string) => void; onRemove: () => void }) {
  const { openSearch } = useApp();
  const t = useT();
  const r = it.ref;
  const [note, setNote] = useState(it.note);

  let body: React.ReactNode = null;
  let link: React.ReactNode = null;
  switch (it.kind) {
    case "answer":
      body = r.text ? <CitedBlock text={r.text} sources={r.sources ?? []} compact /> : null;
      if (r.chat_id) link = <Link to={`/fragen/${r.chat_id}`} className="small">{t("Chat öffnen")}</Link>;
      break;
    case "excerpt":
      body = <div className="source-text clamp" data-selectable>{r.text}</div>;
      link = r.source_type === "transcript" && r.meeting_id
        ? <Link className="small" to={sourceHref(r as any)}><I.Play /> {t("Video")} {fmtTs(r.start ?? 0)}</Link>
        : r.url && <a className="small" href={r.url} target="_blank" rel="noreferrer"><I.External /> PDF {t("S.")} {r.page}</a>;
      break;
    case "agenda":
    case "meeting":
      link = r.meeting_id && <Link className="small" to={`/sitzungen/${r.meeting_id}`}>{r.meeting_title} · {fmtDate(r.date)}</Link>;
      break;
    case "document":
      link = <span className="row small">{r.url && <a href={r.url} target="_blank" rel="noreferrer"><I.External /> PDF</a>}
        {r.meeting_id && <Link to={`/sitzungen/${r.meeting_id}#documents`}>{t("Sitzung")}</Link>}</span>;
      break;
    case "search":
      body = r.top?.length ? <div className="muted small">{t("{n} Top-Treffer gespeichert", { n: r.top.length })}: {r.top.map((x: any) => `${x.meeting_title} (${x.label})`).slice(0, 3).join("; ")}</div> : null;
      link = <button className="btn small" onClick={() => openSearch(r.query)}><I.Search /> {t("Erneut suchen")}</button>;
      break;
    case "chat":
      link = <Link className="small" to={`/fragen/${r.chat_id}`}>{t("Chat öffnen")}</Link>;
      break;
    case "note":
      body = <div style={{ whiteSpace: "pre-wrap" }} data-selectable>{r.text}</div>;
      break;
  }

  return (
    <div className="item-card">
      <div className="row">
        <span className="item-kind">{t(KIND_LABEL[it.kind])}</span>
        <span className="spacer" />
        <button className="btn small" title={t("An Cursorposition in den Bericht einfügen")} onClick={() => onInsert(snippet(it, note))}><I.Insert /> {t("In Bericht")}</button>
        <button className="btn small ghost" title={t("Entfernen")} onClick={onRemove}><I.Trash /></button>
      </div>
      {it.kind !== "note" && <div className="item-title">{it.title}</div>}
      {body}
      <div className="row" style={{ marginTop: ".3rem" }}>{link}</div>
      <input className="input small" style={{ marginTop: ".4rem", padding: ".25rem .5rem" }} placeholder={t("Notiz …")} value={note}
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
