import { useEffect, useState } from "react";
import { Link, useNavigate, useOutletContext } from "react-router-dom";
import { type MeetingListItem, api, fmtDate } from "../api";
import * as I from "../components/Icons";
import type { ShellCtx } from "../components/Layout";
import { useApp } from "../context";
import { meetingTitle, useLang, useT } from "../i18n";

export default function Home() {
  const { user, openSearch } = useApp();
  const t = useT();
  const { lang } = useLang();
  const { projects } = useOutletContext<ShellCtx>();
  const nav = useNavigate();
  const [meetings, setMeetings] = useState<MeetingListItem[] | null>(null);

  useEffect(() => { api.meetings().then(setMeetings).catch(() => setMeetings([])); }, []);
  const today = new Date().toISOString().slice(0, 10);
  const recent = (meetings ?? []).filter((m) => !m.cancelled && m.date && m.date <= today).slice(0, 6);
  const next = (meetings ?? []).filter((m) => !m.cancelled && m.date && m.date > today).reverse()[0];

  return (
    <div className="page-narrow">
      <h1>{t("Ratsarchiv des Gemeinderates")}</h1>
      <div className="intro">
        <p>{t("Grüezi {name}. Sitzungsvideos, Protokolle und Dokumente des Gemeinderats an einem Ort: durchsuchen, Fragen stellen und Ergebnisse für Ihren Bericht sammeln. Jede KI-Antwort ist mit der Quelle belegt.", { name: user.name.split(" ")[0] })}</p>
      </div>

      <div className="tiles">
        <button className="tile" onClick={() => openSearch("")}>
          <I.Search /><strong>{t("Suche")}</strong>
          <span>{t("Begriffe, Namen und Geschäfte in allen Sitzungen finden – auch sinngemäss.")}</span>
        </button>
        <button className="tile" onClick={() => nav("/fragen", { state: { fresh: Date.now() } })}>
          <span className="ai chip yellow"><I.Sparkle /> KI</span>
          <I.Chat /><strong>{t("Fragen")}</strong>
          <span>{t("Fragen in eigenen Worten stellen. Antworten nur aus den Quellen, mit Belegen.")}</span>
        </button>
        <button className="tile" onClick={() => nav("/planen")}>
          <I.Folder /><strong>{t("Planen")}</strong>
          <span>{t("Antworten, Traktanden und Dokumente in Projekten sammeln und den Bericht schreiben.")}</span>
        </button>
      </div>

      <div className="home-grid">
        <section>
          <h2 style={{ marginBottom: 12 }}>{t("Letzte Gemeinderatssitzungen")}</h2>
          <table className="dt">
            <thead><tr><th>{t("Datum")}</th><th>{t("Sitzung")}</th><th /></tr></thead>
            <tbody>
              {meetings === null && <tr><td colSpan={3} className="muted">{t("Lade …")}</td></tr>}
              {meetings && recent.length === 0 && <tr><td colSpan={3} className="muted">{t("Noch keine Sitzungen geladen")} (<code>gr-rag scrape</code>).</td></tr>}
              {recent.map((m) => (
                <tr key={m.id}>
                  <td className="date-badge">{fmtDate(m.date)}</td>
                  <td><Link className="title" to={`/sitzungen/${m.id}`}>{meetingTitle(m.title, lang)}</Link></td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    {m.has_transcript && <span className="chip yellow" title={t("Video mit Transkript")}><I.Video /></span>}{" "}
                    {m.has_protokoll && <span className="chip" title={t("Protokoll")}><I.Doc /></span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small"><Link to="/sitzungen">{t("Alle Sitzungen")}</Link></p>
          {next && (
            <>
              <h3 style={{ marginTop: 24 }}>{t("Nächste Gemeinderatssitzung")}</h3>
              <p className="small">{fmtDate(next.date)}, {next.start} {t("Uhr")} – {meetingTitle(next.title, lang)}</p>
            </>
          )}
        </section>
        <section>
          <h2 style={{ marginBottom: 12 }}>{t("Meine Projekte")}</h2>
          <table className="dt">
            <thead><tr><th>{t("Projekt")}</th><th>{t("Kategorie")}</th></tr></thead>
            <tbody>
              {projects.length === 0 && <tr><td colSpan={2} className="muted">{t("Noch keine Projekte. Speichern Sie Antworten oder Traktanden mit «+ Projekt».")}</td></tr>}
              {projects.slice(0, 6).map((p) => (
                <tr key={p.id}>
                  <td><Link className="title" to={`/planen/${p.id}`}>{p.title}</Link></td>
                  <td className="muted">{p.category}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </div>
  );
}
