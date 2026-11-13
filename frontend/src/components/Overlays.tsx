import { useEffect, useMemo, useRef, useState } from "react";
import { type Project, type Source, type SourceType, api } from "../api";
import { type NewItem, useApp } from "../context";
import { useT } from "../i18n";
import * as I from "./Icons";
import { SourceCard } from "./Sources";

/* ------------------------------------------------------------------ global search */

export function SearchOverlay({ initial, meetingId, onClose }: { initial: string; meetingId?: string; onClose: () => void }) {
  const { addToProject } = useApp();
  const t = useT();
  const [q, setQ] = useState(initial);
  const [types, setTypes] = useState<SourceType[]>([]);
  const [onlyMeeting, setOnlyMeeting] = useState(!!meetingId);
  const [results, setResults] = useState<Source[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); if (initial) run(initial); /* eslint-disable-next-line */ }, []);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  useEffect(() => { if (q.trim()) run(q); /* eslint-disable-next-line */ }, [types, onlyMeeting]);

  async function run(query: string) {
    if (!query.trim()) return;
    setBusy(true); setError(null);
    try {
      setResults(await api.search(query, { types, meeting_id: onlyMeeting ? meetingId : undefined, limit: 25 }));
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  const terms = useMemo(() => q.toLowerCase().split(/\s+/).filter((t) => t.length > 2), [q]);
  const toggle = (t: SourceType) => setTypes((c) => (c.includes(t) ? c.filter((x) => x !== t) : [...c, t]));

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-label={t("Suche")}>
        <form className="modal-head yellow" onSubmit={(e) => { e.preventDefault(); run(q); }}>
          <I.Search />
          <input ref={inputRef} className="search-input" placeholder={t("Begriff, Name, Geschäftsnummer … (semantische Suche)")}
                 value={q} onChange={(e) => setQ(e.target.value)} />
          <button className="btn primary" disabled={!q.trim() || busy}>{t("Suchen")}</button>
          <button type="button" className="btn ghost" onClick={onClose} aria-label={t("Schliessen")}><I.Close /></button>
        </form>
        <div className="modal-body">
          <div className="row wrap" style={{ margin: ".75rem 0" }}>
            <span className="muted small">{t("Quellen")}:</span>
            {(["transcript", "protokoll", "dokument"] as SourceType[]).map((k) => (
              <button key={k} className={`btn small ${types.includes(k) ? "primary" : ""}`} onClick={() => toggle(k)}>
                {t({ transcript: "Video-Transkripte", protokoll: "Protokolle", dokument: "Dokumente" }[k])}
              </button>
            ))}
            {meetingId && (
              <label className="row small"><input type="checkbox" checked={onlyMeeting} onChange={(e) => setOnlyMeeting(e.target.checked)} /> {t("nur diese Sitzung")}</label>
            )}
            <span className="spacer" />
            {results && results.length > 0 && (
              <button className="btn small" onClick={() => addToProject({
                kind: "search", title: `${t("Suche")}: «${q}»`,
                ref: { query: q, types, meeting_id: onlyMeeting ? meetingId : undefined,
                       top: results.slice(0, 5).map((r) => ({ ...r })) },
              })}><I.Folder /> {t("Suche in Projekt speichern")}</button>
            )}
          </div>
          {error && <div className="notice error">{error}</div>}
          {busy && <div className="muted">{t("Suche …")}</div>}
          {results && !busy && results.length === 0 && <div className="empty">{t("Keine Treffer.")}</div>}
          <div className="sources">
            {results?.map((r) => <SourceCard key={r.id} s={{ ...r, text: highlightPlain(r.text, terms) }} clamp />)}
          </div>
          {!results && !busy && (
            <p className="muted small">
              {t("Tipp: Markieren Sie irgendwo im Archiv einen Text (z. B. in einem Transkript oder einer Zusammenfassung), um direkt danach zu suchen.")}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// keep plain text (SourceCard renders text, not HTML); just trim long texts around first hit
function highlightPlain(text: string, terms: string[]) {
  const lower = text.toLowerCase();
  const i = terms.map((t) => lower.indexOf(t)).filter((x) => x >= 0).sort((a, b) => a - b)[0];
  if (i === undefined || i < 160) return text;
  return "… " + text.slice(i - 120);
}

/* ------------------------------------------------------------------ add to project */

export function AddToProjectModal({ item, onClose }: { item: NewItem; onClose: () => void }) {
  const { toast } = useApp();
  const t = useT();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("");
  const [note, setNote] = useState(item.note ?? "");
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.projects().then(setProjects).catch(() => setProjects([])); }, []);
  const categories = [...new Set((projects ?? []).map((p) => p.category))];

  async function addTo(pid: number, ptitle: string) {
    setBusy(true);
    try {
      await api.addItem(pid, { ...item, note });
      toast(t("Zu «{p}» hinzugefügt", { p: ptitle }), { to: `/planen/${pid}`, label: t("Öffnen") });
      onClose();
    } finally { setBusy(false); }
  }

  async function createAndAdd() {
    if (!title.trim()) return;
    setBusy(true);
    try {
      const p = await api.createProject(title.trim(), category.trim() || "Allgemein");
      await addTo(p.id, p.title);
    } finally { setBusy(false); }
  }

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal small" role="dialog" aria-label={t("Zu Projekt hinzufügen")}>
        <div className="modal-head yellow"><I.Folder /><h3>{t("Zu Projekt hinzufügen")}</h3><span className="spacer" />
          <button className="btn ghost" onClick={onClose}><I.Close /></button></div>
        <div className="modal-body stack">
          <div className="panel" style={{ padding: "10px 14px" }}>
            <div className="item-kind">{item.kind}</div>
            <div>{item.title}</div>
          </div>
          <textarea className="textarea" style={{ minHeight: "3.2rem" }} placeholder={t("Notiz (optional)")} value={note} onChange={(e) => setNote(e.target.value)} />
          {projects === null ? <div className="muted">{t("Lade Projekte …")}</div> : projects.length > 0 && (
            <div>
              {categories.map((c) => (
                <div key={c}>
                  <div className="cat-title">{c}</div>
                  {projects.filter((p) => p.category === c).map((p) => (
                    <button key={p.id} className="project-link" style={{ width: "100%", border: 0, background: "none" }}
                            disabled={busy} onClick={() => addTo(p.id, p.title)}>
                      <span>{p.title}</span><span className="muted small">{t("{n} Einträge", { n: p.n_items ?? 0 })}</span>
                    </button>
                  ))}
                </div>
              ))}
            </div>
          )}
          <div className="cat-title">{t("Neues Projekt")}</div>
          <input className="input" placeholder={t("Titel, z. B. «Bericht Schulraumplanung»")} value={title} onChange={(e) => setTitle(e.target.value)} />
          <input className="input" list="cats" placeholder={t("Kategorie, z. B. Bildung, Finanzen, Verkehr")} value={category} onChange={(e) => setCategory(e.target.value)} />
          <datalist id="cats">{categories.map((c) => <option key={c} value={c} />)}</datalist>
          <button className="btn primary" disabled={busy || !title.trim()} onClick={createAndAdd}><I.Plus /> {t("Erstellen & hinzufügen")}</button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ select text -> search */

export function SelectionPopover() {
  const { openSearch, addToProject } = useApp();
  const t = useT();
  const [sel, setSel] = useState<{ text: string; x: number; y: number } | null>(null);

  useEffect(() => {
    const onUp = () => {
      setTimeout(() => {
        const s = window.getSelection();
        const text = s?.toString().trim() ?? "";
        if (!s || !text || text.length < 3 || text.length > 300 || s.rangeCount === 0) return setSel(null);
        const node = s.anchorNode?.parentElement;
        if (!node?.closest("[data-selectable]")) return setSel(null);
        const r = s.getRangeAt(0).getBoundingClientRect();
        setSel({ text, x: r.left + window.scrollX + r.width / 2, y: r.top + window.scrollY - 44 });
      }, 10);
    };
    const onDown = (e: MouseEvent) => { if (!(e.target as HTMLElement).closest(".sel-pop")) setSel(null); };
    document.addEventListener("mouseup", onUp);
    document.addEventListener("mousedown", onDown);
    return () => { document.removeEventListener("mouseup", onUp); document.removeEventListener("mousedown", onDown); };
  }, []);

  if (!sel) return null;
  return (
    <div className="sel-pop" style={{ left: sel.x, top: sel.y, transform: "translateX(-50%)" }}>
      <button onClick={() => { openSearch(sel.text); setSel(null); }}><I.Search /> {t("Im ganzen Archiv suchen")}</button>
      <button onClick={() => { addToProject({ kind: "note", title: `${t("Zitat")}: «${sel.text.slice(0, 80)}»`, ref: { text: sel.text, page: location.pathname } }); setSel(null); }}>
        <I.Plus /> {t("Projekt")}
      </button>
    </div>
  );
}
