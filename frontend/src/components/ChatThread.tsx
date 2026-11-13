import { useEffect, useRef, useState } from "react";
import { type Chat, type Filters, type Message, type SourceType, api, ask, fmtDate } from "../api";
import { useApp } from "../context";
import { useLang, useT } from "../i18n";
import * as I from "./Icons";
import { CitedBlock } from "./Sources";

const EXAMPLES = {
  de: ["Was wurde zum Schulraum diskutiert?", "Wie hat der Gemeinderat über das Budget abgestimmt?",
       "Was wurde zu den Velowegen gesagt?", "Was wurde zur digitalen Verwaltung gesagt?"],
  en: ["What was discussed about school space?", "How did the council vote on the budget?",
       "What was said about the cycle lanes?", "What was said about digital administration?"],
};

const TYPE_LABEL: Record<SourceType, string> = { transcript: "Video", protokoll: "Protokolle", dokument: "Dokumente" };

type Props = {
  chatId?: number | null;
  meetingId?: string;
  meetingTitle?: string;
  initialQuestion?: string;
  initialTypes?: SourceType[];
  onCreated?: (c: Chat) => void;
  onChanged?: () => void;
  compactHead?: React.ReactNode;
};

export default function ChatThread({ chatId, meetingId, meetingTitle, initialQuestion, initialTypes, onCreated, onChanged, compactHead }: Props) {
  const { addToProject, toast } = useApp();
  const t = useT();
  const { lang } = useLang();
  const [chat, setChat] = useState<Chat | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState<string | null>(null);   // streamed raw text
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [types, setTypes] = useState<SourceType[]>(initialTypes ?? ["transcript", "protokoll", "dokument"]);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
  const sentInitial = useRef(false);
  const localId = useRef<number | null>(null);   // chat created by this thread (don't reload it mid-stream)

  useEffect(() => {
    setError(null);
    if (chatId && chatId === localId.current) return;
    if (chatId) {
      api.chat(chatId).then((c) => { setChat(c); setMessages(c.messages ?? []); }).catch((e) => setError(e.message));
    } else {
      setChat(null); setMessages([]);
    }
  }, [chatId]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages, pending]);

  useEffect(() => {
    if (initialQuestion && !sentInitial.current && !chatId) {
      sentInitial.current = true;
      send(initialQuestion);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuestion]);

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    setBusy(true); setError(null); setInput("");
    try {
      let c = chat;
      if (!c) {
        c = await api.createChat(meetingId, meetingTitle ? `${meetingTitle}: ${q.slice(0, 40)}` : undefined);
        localId.current = c.id;
        setChat(c);
        onCreated?.(c);
      }
      const tmp: Message = { id: -Date.now(), role: "user", content: q, sources: [], grounded: true, created: "" };
      setMessages((m) => [...m, tmp]);
      setPending("");
      const filters: Filters = { source_types: types, date_from: dateFrom || undefined, date_to: dateTo || undefined, meeting_id: meetingId };
      const final = await ask(c.id, q, filters, (tok) => setPending((p) => (p ?? "") + tok), lang);
      setMessages((m) => [...m, final]);
      setChat((cur) => (cur && cur.title === "Neuer Chat" ? { ...cur, title: q.slice(0, 60) } : cur));
      onChanged?.();
    } catch (e: any) {
      setError(e.message?.includes("Connection") || e.message?.includes("ollama")
        ? t("Das Sprachmodell ist nicht erreichbar. Läuft Ollama (ollama serve)?")
        : e.message);
    } finally {
      setPending(null); setBusy(false);
    }
  }

  const toggleType = (t: SourceType) =>
    setTypes((cur) => (cur.includes(t) ? (cur.length > 1 ? cur.filter((x) => x !== t) : cur) : [...cur, t]));

  const saveAnswer = (m: Message, question?: string) =>
    addToProject({
      kind: "answer",
      title: question ? `${t("Frage")}: ${question}` : t("Antwort"),
      ref: { question, text: m.content, sources: m.sources, chat_id: chat?.id },
    });

  return (
    <div className="thread">
      <div className="thread-head">
        {compactHead ?? <b>{chat?.title ?? t("Neue Frage")}</b>}
        {meetingId && <span className="chip yellow">{t("nur")} {meetingTitle ?? t("diese Sitzung")}</span>}
        <span className="spacer" />
        <div className="toggle" role="group" aria-label={t("Quellen")}>
          {(Object.keys(TYPE_LABEL) as SourceType[]).map((k) => (
            <button key={k} className={types.includes(k) ? "on" : ""} onClick={() => toggleType(k)}>{t(TYPE_LABEL[k])}</button>
          ))}
        </div>
        {!meetingId && (
          <div className="row small" lang={lang === "en" ? "en-GB" : "de-CH"}>
            <input className="input" style={{ width: 132, padding: ".25rem .4rem" }} type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} title={t("von")} />
            <span className="muted">–</span>
            <input className="input" style={{ width: 132, padding: ".25rem .4rem" }} type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} title={t("bis")} />
          </div>
        )}
        {chat && messages.length > 0 && (
          <button className="btn small" onClick={() => addToProject({ kind: "chat", title: `Chat: ${chat.title}`, ref: { chat_id: chat.id } })}>
            <I.Folder /> {t("Chat speichern")}
          </button>
        )}
      </div>

      <div className="messages">
        {messages.length === 0 && pending === null && (
          <div className="stack" style={{ margin: "auto 0" }}>
            <div className="row"><I.Sparkle /><h3>{t("Fragen an das Ratsarchiv")}</h3></div>
            <p className="muted" style={{ maxWidth: 640 }}>
              {t("Antworten stammen ausschliesslich aus den Transkripten der Sitzungsvideos, den Protokollen und den Sitzungsdokumenten. Jede Aussage ist mit ihrer Quelle verlinkt; Sätze ohne Quelle werden entfernt.")}
            </p>
            {!meetingId && (
              <div className="examples">
                {EXAMPLES[lang].map((e) => <button key={e} onClick={() => send(e)}>{e}</button>)}
              </div>
            )}
          </div>
        )}
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={m.id} className="msg user">{m.content}</div>
          ) : (
            <div key={m.id} className="msg assistant">
              <div className="bubble">
                <CitedBlock text={m.content} sources={m.sources} compact={false} translate={m.lang !== "en"} />
                <div className="row" style={{ marginTop: ".5rem" }}>
                  {!m.grounded && <span className="chip grey">{t("keine Quelle gefunden")}</span>}
                  {!!m.removed && <span className="muted small">{t("{n} Satz/Sätze ohne Quelle entfernt", { n: m.removed })}</span>}
                  <span className="spacer" />
                  {m.grounded && (
                    <button className="btn small" onClick={() => saveAnswer(m, messages[i - 1]?.content)}>
                      <I.Plus /> {t("Zu Projekt")}
                    </button>
                  )}
                  <button className="btn small ghost" onClick={() => { navigator.clipboard?.writeText(m.content); toast(t("Antwort kopiert")); }}>{t("Kopieren")}</button>
                </div>
              </div>
            </div>
          ),
        )}
        {pending !== null && (
          <div className="msg assistant"><div className="bubble">
            {pending ? <span className="typing">{pending}</span> : <span className="typing">{t("Suche in Transkripten und Protokollen")} </span>}
          </div></div>
        )}
        {error && <div className="notice error">{error}</div>}
        <div ref={endRef} />
      </div>

      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(input); }}>
        <textarea className="textarea" rows={1} placeholder={t("Ihre Frage …")} value={input} disabled={busy}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }} />
        <button className="btn primary" disabled={busy || !input.trim()}>{t("Fragen")}</button>
      </form>
      {dateFrom || dateTo ? <div className="muted small" style={{ padding: "0 1rem .5rem" }}>{t("Zeitraum")}: {fmtDate(dateFrom) || "…"} – {fmtDate(dateTo) || "…"}</div> : null}
    </div>
  );
}
