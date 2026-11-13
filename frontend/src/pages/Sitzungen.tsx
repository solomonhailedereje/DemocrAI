import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { type MeetingListItem, api, fmtDate } from "../api";
import * as I from "../components/Icons";
import { meetingTitle, useLang, useT } from "../i18n";

export default function Sitzungen() {
  const [list, setList] = useState<MeetingListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [year, setYear] = useState<string>("alle");
  const [q, setQ] = useState("");
  const [onlyVideo, setOnlyVideo] = useState(false);
  const t = useT();

  useEffect(() => { api.meetings().then(setList).catch((e) => setError(e.message)); }, []);

  const today = new Date().toISOString().slice(0, 10);
  const years = useMemo(() => [...new Set((list ?? []).map((m) => m.date?.slice(0, 4)).filter(Boolean))] as string[], [list]);
  const shown = (list ?? []).filter((m) =>
    (year === "alle" || m.date?.startsWith(year)) && (!onlyVideo || m.has_video) &&
    (!q || m.title.toLowerCase().includes(q.toLowerCase())));
  const upcoming = shown.filter((m) => (m.date ?? "") > today).reverse();
  const past = shown.filter((m) => (m.date ?? "") <= today);

  return (
    <div className="page-narrow">
      <h1>{t("Sitzungen")}</h1>
      <p>{t("Die Traktanden, Protokolle und Videoaufzeichnungen der Gemeinderatssitzungen. Mit KI-Zusammenfassung, Kapiteln und durchsuchbarem Transkript, sobald verfügbar.")}</p>
      <div className="row wrap" style={{ margin: "16px 0 24px" }}>
        <input className="input" style={{ width: 260 }} placeholder={t("Titel filtern")} value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="input" style={{ width: 150 }} value={year} onChange={(e) => setYear(e.target.value)}>
          <option value="alle">{t("Alle Jahre")}</option>
          {years.map((y) => <option key={y}>{y}</option>)}
        </select>
        <label className="row small"><input type="checkbox" checked={onlyVideo} onChange={(e) => setOnlyVideo(e.target.checked)} /> {t("nur mit Video")}</label>
      </div>
      {error && <div className="notice error">{error}</div>}

      {upcoming.length > 0 && (
        <>
          <h2>{t("Nächste Gemeinderatssitzungen")}</h2>
          <Table rows={upcoming.slice(0, 3)} />
        </>
      )}
      <h2 style={{ marginTop: 40 }}>{t("Letzte Gemeinderatssitzungen")} <span className="muted small">({past.length})</span></h2>
      {list === null && !error ? <p className="muted">{t("Lade …")}</p> : <Table rows={past} />}
    </div>
  );
}

function Table({ rows }: { rows: MeetingListItem[] }) {
  const t = useT();
  const { lang } = useLang();
  return (
    <table className="dt" style={{ marginTop: 12 }}>
      <thead><tr><th style={{ width: "9rem" }}>{t("Datum")}</th><th>{t("Sitzung")}</th><th style={{ textAlign: "right" }}>{t("Verfügbar")}</th></tr></thead>
      <tbody>
        {rows.length === 0 && <tr><td colSpan={3} className="muted">{t("Keine Sitzungen gefunden.")}</td></tr>}
        {rows.map((m) => (
          <tr key={m.id}>
            <td className="date-badge">{fmtDate(m.date)}{m.start && <div className="muted small">{m.start}{m.end ? ` – ${m.end}` : ""} {t("Uhr")}</div>}</td>
            <td>{m.cancelled ? <span className="muted">{meetingTitle(m.title, lang)}</span> : <Link className="title" to={`/sitzungen/${m.id}`}>{meetingTitle(m.title, lang)}</Link>}</td>
            <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
              {m.n_agenda > 0 && <span className="chip" title={t("Traktanden")}><I.Agenda /> {m.n_agenda}</span>}{" "}
              {m.has_video && <span className={`chip ${m.has_transcript ? "yellow" : "grey"}`} title={m.has_transcript ? t("Video mit Transkript") : t("Video, noch nicht transkribiert")}><I.Video /> Video</span>}{" "}
              {m.has_protokoll && <span className="chip"><I.Doc /> {t("Protokoll")}</span>}{" "}
              {m.has_summary && <span className="chip green"><I.Sparkle /> {t("Übersicht")}</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
