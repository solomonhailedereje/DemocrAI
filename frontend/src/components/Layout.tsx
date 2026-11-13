import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { type Chat, type Project, type User, api } from "../api";
import { type ChatDrawerOpts, Ctx, type NewItem } from "../context";
import { useLang, useT } from "../i18n";
import ChatThread from "./ChatThread";
import * as I from "./Icons";
import { AddToProjectModal, SearchOverlay, SelectionPopover } from "./Overlays";

export type ShellCtx = { refreshChats: () => void; refreshProjects: () => void; projects: Project[] };

const SECTION: Record<string, string> = { sitzungen: "Sitzungen", fragen: "Fragen", planen: "Planen" };

export default function Layout({ user, onLogout }: { user: User; onLogout: () => void }) {
  const nav = useNavigate();
  const loc = useLocation();
  const t = useT();
  const { lang, setLang } = useLang();
  const [search, setSearch] = useState<{ q: string; meetingId?: string } | null>(null);
  const [drawer, setDrawer] = useState<(ChatDrawerOpts & { key: number }) | null>(null);
  const [adding, setAdding] = useState<NewItem | null>(null);
  const [toastMsg, setToastMsg] = useState<{ msg: string; link?: { to: string; label: string } } | null>(null);
  const [chats, setChats] = useState<Chat[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [modal, setModal] = useState<"about" | "help" | null>(null);
  const [crumbTitle, setCrumbTitle] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  const refreshChats = useCallback(() => { api.chats().then(setChats).catch(() => {}); }, []);
  const refreshProjects = useCallback(() => { api.projects().then(setProjects).catch(() => {}); }, []);
  useEffect(() => { refreshChats(); refreshProjects(); }, [refreshChats, refreshProjects]);
  useEffect(() => { setCrumbTitle(null); setMenuOpen(false); window.scrollTo(0, 0); }, [loc.pathname]);

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setSearch({ q: "" }); }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);

  const toast = (msg: string, link?: { to: string; label: string }) => {
    setToastMsg({ msg, link });
    setTimeout(() => setToastMsg(null), 3500);
  };
  const logout = async () => { await api.logout().catch(() => {}); onLogout(); };

  const ctx = {
    user,
    openSearch: (q = "", opts?: { meetingId?: string }) => setSearch({ q, meetingId: opts?.meetingId }),
    openChat: (opts: ChatDrawerOpts = {}) => setDrawer({ ...opts, key: Date.now() }),
    addToProject: (item: NewItem) => setAdding(item),
    toast,
    logout,
    setCrumbTitle,
  };

  const section = loc.pathname.split("/")[1];
  const onFragen = section === "fragen";
  const onPlanen = section === "planen";
  const cats = [...new Set(projects.map((p) => p.category))];

  return (
    <Ctx.Provider value={ctx}>
      <header className="header">
        <Link to="/" className="brand" aria-label={t("Ratsarchiv Startseite")}><I.Wordmark /></Link>
        <button className="menu-btn" onClick={() => setMenuOpen(!menuOpen)} aria-expanded={menuOpen}><I.Bars /> {t("MENÜ")}</button>
        <nav className="util" aria-label="Service">
          <button className="search-trigger" onClick={() => setSearch({ q: "" })}><I.Search /><span className="label-text">{t("Suche")}</span></button>
          <button onClick={() => setModal("help")}><I.Help /><span className="label-text">{t("Hilfe")}</span></button>
          <button onClick={() => setModal("about")}><I.Info /><span className="label-text">{t("Über")}</span></button>
          <a href="https://www.duebendorf.ch/sitzung" target="_blank" rel="noreferrer"><I.External /><span className="label-text">duebendorf.ch</span></a>
          <span className="lang-switch" role="group" aria-label="Sprache / Language">
            <button className={lang === "de" ? "on" : ""} onClick={() => setLang("de")} aria-pressed={lang === "de"}>DE</button>
            <button className={lang === "en" ? "on" : ""} onClick={() => setLang("en")} aria-pressed={lang === "en"}>EN</button>
          </span>
          <button onClick={logout} title={`${t("Abmelden")} (${user.email})`}><I.User /><span className="label-text">{user.name} · {t("Abmelden")}</span></button>
        </nav>
      </header>
      <nav className="crumbs" aria-label={t("Brotkrumen")}>
        <Link to="/">Home</Link>
        {SECTION[section] && <><I.AngleRight />
          {crumbTitle ? <Link to={`/${section}`}>{t(SECTION[section])}</Link> : <span className="current">{t(SECTION[section])}</span>}</>}
        {crumbTitle && <><I.AngleRight /><span className="current">{crumbTitle}</span></>}
      </nav>

      <div className="shell">
        <aside className={`subnav ${menuOpen ? "open" : ""}`} aria-label={t("Navigation")}>
          <NavLink to="/" end><span className="label">{t("Übersicht")}</span></NavLink>
          <NavLink to="/sitzungen"><span className="label">{t("Sitzungen")}</span></NavLink>
          <NavLink to="/fragen"><span className="label">{t("Fragen")}</span></NavLink>
          {onFragen && (
            <>
              <button className="sub small-entry" onClick={() => nav("/fragen", { state: { fresh: Date.now() } })}><I.Plus /> {t("Neuer Chat")}</button>
              {chats.map((c) => (
                <NavLink key={c.id} to={`/fragen/${c.id}`} className="sub small-entry" title={c.title}>
                  <span className="label">{c.title.length > 30 ? c.title.slice(0, 30) + "…" : c.title}</span>
                </NavLink>
              ))}
            </>
          )}
          <NavLink to="/planen"><span className="label">{t("Planen")}</span></NavLink>
          {onPlanen && (
            <>
              <button className="sub small-entry" onClick={() => nav("/planen", { state: { create: Date.now() } })}><I.Plus /> {t("Neues Projekt")}</button>
              {cats.map((cat) => (
                <div key={cat}>
                  <div className="group-title">{cat}</div>
                  {projects.filter((p) => p.category === cat).map((p) => (
                    <NavLink key={p.id} to={`/planen/${p.id}`} className="sub small-entry">
                      <span className="label">{p.title}</span> <span className="muted">({p.n_items})</span>
                    </NavLink>
                  ))}
                </div>
              ))}
            </>
          )}
          <button onClick={() => setSearch({ q: "" })}><span className="label">{t("Suche")}</span></button>
          {!onFragen && chats.length > 0 && (
            <>
              <div className="group-title">{t("Letzte Chats")}</div>
              {chats.slice(0, 3).map((c) => (
                <Link key={c.id} to={`/fragen/${c.id}`} className="sub small-entry">{c.title.length > 30 ? c.title.slice(0, 30) + "…" : c.title}</Link>
              ))}
            </>
          )}
        </aside>
        <main className="content">
          <Outlet context={{ refreshChats, refreshProjects, projects } satisfies ShellCtx} />
        </main>
      </div>

      <footer className="footer">
        <div className="footer-inner">
          <div className="footer-cols">
            <div>
              <h3>Ratsarchiv · DemocrAI</h3>
              <div>{t("Durchsuchbare Sitzungen des Gemeinderats Dübendorf")}</div>
              <div className="muted small" style={{ marginTop: 8 }}>{t("Forschungsprojekt – kein offizielles Angebot der Stadt Dübendorf.")}</div>
            </div>
            <div>
              <h3>{t("Quellen")}</h3>
              <a href="https://www.duebendorf.ch/sitzung" target="_blank" rel="noreferrer">{t("Sitzungen auf duebendorf.ch")}</a>
              <a href="https://www.duebendorf.ch/geschaefte" target="_blank" rel="noreferrer">{t("Geschäfte des Gemeinderats")}</a>
              <div className="muted small" style={{ marginTop: 8 }}>{t("Massgebend sind die offiziellen Protokolle.")}</div>
            </div>
            <div>
              <h3>Links</h3>
              <Link to="/sitzungen">{t("Sitzungen")}</Link>
              <Link to="/fragen">{t("Fragen")}</Link>
              <Link to="/planen">{t("Planen")}</Link>
              <a href="#" onClick={(e) => { e.preventDefault(); setModal("help"); }}>{t("Hilfe")}</a>
            </div>
          </div>
          <div className="footer-bottom">
            <span>© {new Date().getFullYear()} DemocrAI</span>
            <a href="#" onClick={(e) => { e.preventDefault(); setModal("about"); }}>{t("Über das Projekt")}</a>
            <a href="#" onClick={(e) => { e.preventDefault(); logout(); }}>{t("Abmelden")}</a>
          </div>
        </div>
      </footer>

      {drawer && (
        <>
          <div className="drawer-backdrop" onClick={() => setDrawer(null)} />
          <aside className="drawer" aria-label={t("Fragen (KI)")}>
            <ChatThread key={drawer.key} meetingId={drawer.meetingId} meetingTitle={drawer.meetingTitle}
                        initialQuestion={drawer.question} initialTypes={drawer.sourceTypes as any}
                        onChanged={refreshChats}
                        compactHead={<>
                          <button className="btn ghost small" onClick={() => setDrawer(null)} aria-label={t("Schliessen")}><I.Close /></button>
                          <b className="row"><I.Sparkle /> {t("Fragen (KI)")}</b>
                        </>} />
          </aside>
        </>
      )}
      {search && <SearchOverlay initial={search.q} meetingId={search.meetingId} onClose={() => setSearch(null)} />}
      {adding && <AddToProjectModal item={adding} onClose={() => { setAdding(null); refreshProjects(); }} />}
      {modal && <InfoModal kind={modal} onClose={() => setModal(null)} />}
      <SelectionPopover />
      {toastMsg && (
        <div className="toast">{toastMsg.msg}{toastMsg.link && <Link to={toastMsg.link.to} onClick={() => setToastMsg(null)}>{toastMsg.link.label}</Link>}</div>
      )}
    </Ctx.Provider>
  );
}

function InfoModal({ kind, onClose }: { kind: "about" | "help"; onClose: () => void }) {
  const t = useT();
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal small">
        <div className="modal-head yellow"><h3>{kind === "about" ? t("Über das Ratsarchiv") : t("Hilfe")}</h3><span className="spacer" />
          <button className="btn ghost" onClick={onClose} aria-label={t("Schliessen")}><I.Close /></button></div>
        <div className="modal-body stack">
          {kind === "about" ? (
            <>
              <p>{t("Das Ratsarchiv macht die Sitzungen des Gemeinderats Dübendorf durchsuchbar: Videoaufzeichnungen (automatisch aus dem Schweizerdeutschen transkribiert), offizielle Protokolle und Sitzungsdokumente.")}</p>
              <p>{t("KI-Antworten und Zusammenfassungen verwenden nur diese Quellen. Jede Aussage ist mit ihrer Quelle verlinkt; Sätze ohne Quelle werden automatisch entfernt.")}</p>
              <p>{t("Englisch: Benutzeroberfläche, KI-Antworten und Zusammenfassungen lassen sich auf Englisch anzeigen (maschinelle Übersetzung). Das deutsche Original bleibt massgebend und ist jederzeit abrufbar.")}</p>
              <p className="muted small">{t("DemocrAI ist ein Forschungsprojekt und kein offizielles Angebot der Stadt Dübendorf. Transkripte können Fehler enthalten – massgebend sind die Protokolle und die Videoaufzeichnung.")}</p>
            </>
          ) : (
            <>
              <p><b>{t("Suche")}</b> (⌘K): {t("findet Stellen in Videos, Protokollen und Dokumenten – auch sinngemäss.")}</p>
              <p><b>{t("Fragen")}</b>: {t("Antworten zeigen nummerierte Quellen. Klick auf die Nummer zeigt den Auszug, «Im Video» springt zur Stelle.")}</p>
              <p><b>{t("Sitzungen")}</b>: {t("Traktanden, Protokoll, Kapitel und Video mit mitlaufendem Transkript.")}</p>
              <p><b>{t("Planen")}</b>: {t("Antworten, Suchen, Traktanden und Dokumente in Projekten sammeln und daraus den Bericht schreiben.")}</p>
              <p><b>{t("Text markieren")}</b>: {t("markierten Text im ganzen Archiv suchen oder einem Projekt hinzufügen.")}</p>
              <p><b>DE / EN</b>: {t("Sprache der Oberfläche und der KI-Antworten umschalten.")}</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
