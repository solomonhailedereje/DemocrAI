import { Fragment, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { type Cited, type Source, fmtDate, fmtTs, sourceHref } from "../api";
import { useApp } from "../context";
import * as I from "./Icons";

const KIND: Record<string, string> = { transcript: "Video", protokoll: "Protokoll", dokument: "Dokument" };

/** Text with [n] markers rendered as clickable citation chips. */
export function CitedText({ text, onCite, active }: { text: string; onCite?: (n: number) => void; active?: number | null }) {
  return (
    <div className="cited" data-selectable>
      {text.split("\n").filter(Boolean).map((line, li) => (
        <p key={li}>
          {line.split(/(\[\d+\])/g).map((part, i) => {
            const m = part.match(/^\[(\d+)\]$/);
            if (!m) return <Fragment key={i}>{part}</Fragment>;
            const n = Number(m[1]);
            return (
              <button key={i} className={`cite ${active === n ? "on" : ""}`} title={`Quelle ${n} anzeigen`}
                      onClick={() => onCite?.(n)}>{n}</button>
            );
          })}
        </p>
      ))}
    </div>
  );
}

export function SourceCard({ s, n, clamp = true, highlight, onSeek }: {
  s: Source; n?: number; clamp?: boolean; highlight?: boolean; onSeek?: (t: number) => void;
}) {
  const { addToProject } = useApp();
  const [open, setOpen] = useState(!clamp);
  const isVideo = s.source_type === "transcript";
  const internal = isVideo && s.meeting_id;
  const addExcerpt = () =>
    addToProject({
      kind: "excerpt",
      title: `${KIND[s.source_type]}: ${s.meeting_title} ${fmtDate(s.date)} – ${s.label}`,
      ref: { ...s, text: s.text },
    });

  return (
    <div className={`source ${s.source_type} ${highlight ? "flash" : ""}`} id={n ? `src-${s.id}` : undefined}>
      <div className="source-head">
        {n !== undefined && <span className="n">[{n}]</span>}
        <span className="chip grey">{isVideo ? <I.Video /> : <I.Doc />} {KIND[s.source_type]}</span>
        {s.meeting_id
          ? <Link to={`/sitzungen/${s.meeting_id}`}><b>{s.meeting_title}</b></Link>
          : <b>{s.meeting_title}</b>}
        <span className="muted">{fmtDate(s.date)}</span>
        <span className="muted">·</span>
        <span>{isVideo ? `Video ${fmtTs(s.start ?? 0)}–${fmtTs(s.end ?? 0)}` : `${s.doc_title ?? ""}, S. ${s.page}`}</span>
        <span className="spacer" />
        {isVideo && onSeek ? (
          <button className="btn small" onClick={() => onSeek(s.start ?? 0)}><I.Play /> Abspielen</button>
        ) : internal ? (
          <Link className="btn small" to={sourceHref(s)}><I.Play /> Im Video</Link>
        ) : (
          <a className="btn small" href={s.url} target="_blank" rel="noreferrer"><I.External /> {isVideo ? "YouTube" : "PDF"}</a>
        )}
        <button className="btn small ghost" title="Zu Projekt hinzufügen" onClick={addExcerpt}><I.Plus /> Projekt</button>
      </div>
      <div className={`source-text ${open ? "" : "clamp"}`} data-selectable onClick={() => setOpen(true)}>{s.text}</div>
      {isVideo && <div className="muted small">Automatische Transkription (Schweizerdeutsch → Hochdeutsch), kann Fehler enthalten.</div>}
      {s.support !== undefined && s.support < 0.3 && (
        <div className="warn">⚠ Geringe Übereinstimmung zwischen Aussage und Auszug – bitte im Original prüfen.</div>
      )}
    </div>
  );
}

/** Answer/summary text + its numbered sources; clicking [n] highlights the source. */
export function CitedBlock({ text, sources, onSeek, compact }: {
  text: string; sources: (Source & { n?: number })[]; onSeek?: (t: number) => void; compact?: boolean;
}) {
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
      <CitedText text={text} onCite={cite} active={active} />
      {numbered.length > 0 && (
        compact && !showAll ? (
          <button className="btn small ghost" onClick={() => setShowAll(true)}>{numbered.length} Quelle{numbered.length > 1 ? "n" : ""} anzeigen</button>
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
