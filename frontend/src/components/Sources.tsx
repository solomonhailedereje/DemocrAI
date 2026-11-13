import { Fragment, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { type Cited, type Source, fmtDate, fmtTs, sourceHref } from "../api";
import { useApp } from "../context";
import { meetingTitle, useContentTranslation, useLang, useT } from "../i18n";
import * as I from "./Icons";

const KIND: Record<string, string> = { transcript: "Video", protokoll: "Protokoll", dokument: "Dokument" };

/** Text with [n] markers as clickable citation chips; machine-translated when the UI is English. */
export function CitedText({ text, onCite, active, translate = true }: {
  text: string; onCite?: (n: number) => void; active?: number | null; translate?: boolean;
}) {
  const t = useT();
  const { active: on, tr, pending, failed } = useContentTranslation([text], translate);
  const [orig, setOrig] = useState(false);
  const shown = on && !orig ? tr(text) : text;
  return (
    <div className="cited" data-selectable>
      {shown.split("\n").filter(Boolean).map((line, li) => (
        <p key={li}>
          {line.split(/(\[\d+\])/g).map((part, i) => {
            const m = part.match(/^\[(\d+)\]$/);
            if (!m) return <Fragment key={i}>{part}</Fragment>;
            const n = Number(m[1]);
            return (
              <button key={i} className={`cite ${active === n ? "on" : ""}`} title={t("Quelle {n} anzeigen", { n })}
                      onClick={() => onCite?.(n)}>{n}</button>
            );
          })}
        </p>
      ))}
      {on && (
        <div className="mt-note">
          {pending ? t("Wird übersetzt …") : failed(text) ? t("Übersetzung nicht möglich – Original angezeigt.") : (
            <>{t("Maschinelle Übersetzung.")}{" "}
              <button className="linklike" onClick={() => setOrig(!orig)}>{orig ? t("Übersetzung zeigen") : t("Original (Deutsch) zeigen")}</button></>
          )}
        </div>
      )}
    </div>
  );
}

export function SourceCard({ s, n, clamp = true, highlight, onSeek }: {
  s: Source; n?: number; clamp?: boolean; highlight?: boolean; onSeek?: (t: number) => void;
}) {
  const { addToProject } = useApp();
  const t = useT();
  const { lang } = useLang();
  const [open, setOpen] = useState(!clamp);
  const [wantTr, setWantTr] = useState(false);
  const { tr, pending } = useContentTranslation([s.text], wantTr);
  const isVideo = s.source_type === "transcript";
  const internal = isVideo && s.meeting_id;
  const mt = meetingTitle(s.meeting_title, lang);
  const addExcerpt = () =>
    addToProject({
      kind: "excerpt",
      title: `${KIND[s.source_type]}: ${s.meeting_title} ${fmtDate(s.date)} – ${s.label}`,
      ref: { ...s, text: s.text },
    });

  return (
    <div className={`source ${s.source_type} ${highlight ? "flash" : ""}`}>
      <div className="source-head">
        {n !== undefined && <span className="n">[{n}]</span>}
        <span className="chip grey">{isVideo ? <I.Video /> : <I.Doc />} {t(KIND[s.source_type])}</span>
        {s.meeting_id ? <Link to={`/sitzungen/${s.meeting_id}`}><b>{mt}</b></Link> : <b>{mt}</b>}
        <span className="muted">{fmtDate(s.date)}</span>
        <span className="muted">·</span>
        <span>{isVideo ? `Video ${fmtTs(s.start ?? 0)}–${fmtTs(s.end ?? 0)}` : `${s.doc_title ?? ""}, ${t("S.")} ${s.page}`}</span>
        <span className="spacer" />
        {isVideo && onSeek ? (
          <button className="btn small" onClick={() => onSeek(s.start ?? 0)}><I.Play /> {t("Abspielen")}</button>
        ) : internal ? (
          <Link className="btn small" to={sourceHref(s)}><I.Play /> {t("Im Video")}</Link>
        ) : (
          <a className="btn small" href={s.url} target="_blank" rel="noreferrer"><I.External /> {isVideo ? "YouTube" : "PDF"}</a>
        )}
        {lang === "en" && (
          <button className="btn small ghost" onClick={() => { setWantTr(!wantTr); setOpen(true); }}>
            <I.Globe /> {wantTr ? "German only" : "Translate"}
          </button>
        )}
        <button className="btn small ghost" title={t("Zu Projekt hinzufügen")} onClick={addExcerpt}><I.Plus /> {t("Projekt")}</button>
      </div>
      <div className={`source-text ${open ? "" : "clamp"}`} data-selectable onClick={() => setOpen(true)}>{s.text}</div>
      {wantTr && (
        <div className="source-text translated">{pending ? t("Wird übersetzt …") : tr(s.text)}</div>
      )}
      {isVideo && <div className="muted small">{t("Automatische Transkription (Schweizerdeutsch → Hochdeutsch), kann Fehler enthalten.")}</div>}
      {s.support !== undefined && s.support < 0.3 && (
        <div className="warn">⚠ {t("Geringe Übereinstimmung zwischen Aussage und Auszug – bitte im Original prüfen.")}</div>
      )}
    </div>
  );
}

/** Answer/summary text + its numbered sources; clicking [n] highlights the source. */
export function CitedBlock({ text, sources, onSeek, compact, translate = true }: {
  text: string; sources: (Source & { n?: number })[]; onSeek?: (t: number) => void; compact?: boolean; translate?: boolean;
}) {
  const t = useT();
  const [active, setActive] = useState<number | null>(null);
  const [showAll, setShowAll] = useState(!compact);
  const ref = useRef<HTMLDivElement>(null);
  const cite = (n: number) => {
    setActive(n);
    setShowAll(true);
    setTimeout(() => ref.current?.querySelector(`[data-n="${n}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }), 30);
  };
  const numbered = sources.map((s, i) => ({ ...s, n: s.n ?? i + 1 }));
  return (
    <div>
      <CitedText text={text} onCite={cite} active={active} translate={translate} />
      {numbered.length > 0 && (
        compact && !showAll ? (
          <button className="btn small ghost" onClick={() => setShowAll(true)}>
            {numbered.length === 1 ? t("1 Quelle anzeigen") : t("{n} Quellen anzeigen", { n: numbered.length })}</button>
        ) : (
          <div className="sources" ref={ref}>
            {numbered.map((s) => (
              <div key={`${s.id}-${s.n}`} data-n={s.n}>
                <SourceCard s={s} n={s.n} highlight={active === s.n} onSeek={onSeek} />
              </div>
            ))}
          </div>
        )
      )}
    </div>
  );
}

export const citedToProps = (c: Cited) => ({ text: c.text, sources: c.sources.map((s) => ({ ...s.chunk, n: s.n })) });
