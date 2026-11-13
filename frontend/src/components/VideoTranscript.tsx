import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { type Chapter, type Segment, fmtTs } from "../api";
import { useApp } from "../context";
import * as I from "./Icons";

export type VideoHandle = { seek: (t: number) => void };

// Load the YouTube IFrame API once
let ytReady: Promise<void> | null = null;
function loadYT(): Promise<void> {
  if (window.YT?.Player) return Promise.resolve();
  if (!ytReady) {
    ytReady = new Promise((resolve) => {
      (window as any).onYouTubeIframeAPIReady = () => resolve();
      const s = document.createElement("script");
      s.src = "https://www.youtube.com/iframe_api";
      document.head.appendChild(s);
    });
  }
  return ytReady;
}

type Props = { videoId: string | null; segments: Segment[] | null; chapters: Chapter[]; meetingId: string; meetingTitle: string; date: string | null; startAt?: number };

const VideoTranscript = forwardRef<VideoHandle, Props>(function VideoTranscript(
  { videoId, segments, chapters, meetingId, meetingTitle, date, startAt }, ref) {
  const { addToProject } = useApp();
  const holder = useRef<HTMLDivElement>(null);
  const player = useRef<YT.Player | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const [now, setNow] = useState(startAt ?? 0);
  const [follow, setFollow] = useState(true);
  const [filter, setFilter] = useState("");
  const [ready, setReady] = useState(false);

  useImperativeHandle(ref, () => ({
    seek: (t: number) => {
      setNow(t);
      if (player.current?.seekTo) { player.current.seekTo(t, true); player.current.playVideo(); }
    },
  }));

  useEffect(() => {
    if (!videoId || !holder.current) return;
    let cancelled = false;
    const el = document.createElement("div");
    holder.current.innerHTML = "";
    holder.current.appendChild(el);
    loadYT().then(() => {
      if (cancelled) return;
      player.current = new YT.Player(el, {
        videoId,
        playerVars: { start: Math.floor(startAt ?? 0), rel: 0, modestbranding: 1 },
        events: { onReady: () => setReady(true) },
      });
    });
    return () => { cancelled = true; player.current?.destroy?.(); player.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId]);

  // poll current time -> highlight transcript
  useEffect(() => {
    if (!ready) return;
    const id = setInterval(() => {
      const t = player.current?.getCurrentTime?.();
      if (typeof t === "number") setNow(t);
    }, 500);
    return () => clearInterval(id);
  }, [ready]);

  const nowIdx = useMemo(() => {
    if (!segments?.length) return -1;
    let lo = 0, hi = segments.length - 1, ans = -1;
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (segments[mid].start <= now) { ans = mid; lo = mid + 1; } else hi = mid - 1; }
    return ans;
  }, [segments, now]);

  useEffect(() => {
    if (!follow || nowIdx < 0 || filter) return;
    const el = bodyRef.current?.querySelector<HTMLElement>(`[data-i="${nowIdx}"]`);
    const body = bodyRef.current;
    if (el && body) body.scrollTo({ top: el.offsetTop - body.clientHeight / 3, behavior: "smooth" });
  }, [nowIdx, follow, filter]);

  const chapterAt = useMemo(() => {
    const m = new Map<number, Chapter>();
    if (segments) for (const c of chapters) {
      const i = segments.findIndex((s) => s.end > c.start);
      if (i >= 0 && !m.has(i)) m.set(i, c);
    }
    return m;
  }, [segments, chapters]);

  const f = filter.trim().toLowerCase();
  const seek = (t: number) => {
    setNow(t);
    if (player.current?.seekTo) { player.current.seekTo(t, true); player.current.playVideo(); }
  };

  return (
    <div className="video-grid">
      <div>
        <div className="video-box">
          {videoId ? <div ref={holder} /> : <div className="video-placeholder">Für diese Sitzung ist kein Video verfügbar.</div>}
        </div>
        <div className="row small muted" style={{ marginTop: ".4rem" }}>
          <span className="ts">{fmtTs(now)}</span>
          <span className="spacer" />
          {videoId && <a href={`https://www.youtube.com/watch?v=${videoId}&t=${Math.floor(now)}s`} target="_blank" rel="noreferrer"><I.External /> Auf YouTube öffnen</a>}
        </div>
      </div>

      <div className="transcript">
        <div className="transcript-tools">
          <I.Search />
          <input className="input" style={{ padding: ".25rem .5rem" }} placeholder="Im Transkript filtern" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <label className="row small" title="Transkript folgt dem Video"><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> folgen</label>
        </div>
        <div className="transcript-body" ref={bodyRef} data-selectable>
          {!segments && <div className="empty">Noch kein Transkript für diese Sitzung.</div>}
          {segments?.map((s, i) => {
            if (f && !s.text.toLowerCase().includes(f)) return null;
            const ch = chapterAt.get(i);
            return (
              <div key={i}>
                {ch && !f && <div className="chapter-mark">Traktandum {ch.number}: {ch.title.slice(0, 70)}</div>}
                <div className={`seg ${i === nowIdx ? "now" : ""} ${f ? "match" : ""}`} data-i={i} onClick={() => seek(s.start)}
                     onDoubleClick={() => addToProject({ kind: "excerpt", title: `Video: ${meetingTitle} – ${fmtTs(s.start)}`,
                       ref: { source_type: "transcript", meeting_id: meetingId, meeting_title: meetingTitle, date, start: s.start, end: s.end, text: s.text,
                              url: videoId ? `https://www.youtube.com/watch?v=${videoId}&t=${Math.floor(s.start)}s` : undefined } })}>
                  <span className="ts">{fmtTs(s.start)}</span>
                  <span>{f ? highlight(s.text, f) : s.text}</span>
                </div>
              </div>
            );
          })}
        </div>
        <div className="muted small" style={{ padding: ".35rem .6rem", borderTop: "1px solid var(--line)" }}>
          Klick: zur Stelle springen · Doppelklick: Stelle zu Projekt · Text markieren: im Archiv suchen
        </div>
      </div>
    </div>
  );
});

function highlight(text: string, f: string) {
  const i = text.toLowerCase().indexOf(f);
  if (i < 0) return text;
  return <>{text.slice(0, i)}<mark>{text.slice(i, i + f.length)}</mark>{text.slice(i + f.length)}</>;
}

export default VideoTranscript;
