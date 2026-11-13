import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useOutletContext, useParams } from "react-router-dom";
import { api } from "../api";
import ChatThread from "../components/ChatThread";
import * as I from "../components/Icons";
import type { ShellCtx } from "../components/Layout";

export default function Fragen() {
  const { id } = useParams();
  const chatId = id ? Number(id) : null;
  const nav = useNavigate();
  const loc = useLocation();
  const { refreshChats } = useOutletContext<ShellCtx>();
  const fresh = (loc.state as any)?.fresh;
  // Keep the same thread mounted when the URL changes only because this thread just created its chat
  const created = useRef<number | null>(null);
  const [threadKey, setThreadKey] = useState(() => String(chatId ?? `new-${fresh ?? ""}`));
  useEffect(() => {
    if (chatId !== null && chatId === created.current) return;
    created.current = null;
    setThreadKey(String(chatId ?? `new-${fresh ?? ""}`));
  }, [chatId, fresh]);

  async function remove() {
    if (!chatId || !confirm("Diesen Chat löschen?")) return;
    await api.deleteChat(chatId);
    refreshChats();
    nav("/fragen", { state: { fresh: Date.now() } });
  }

  return (
    <div className="page-narrow">
      <div className="row" style={{ alignItems: "flex-start" }}>
        <h1 style={{ flex: 1 }}>Fragen</h1>
        <button className="btn" onClick={() => nav("/fragen", { state: { fresh: Date.now() } })}><I.Plus /> Neuer Chat</button>
        {chatId && <button className="btn" onClick={remove}><I.Trash /> Löschen</button>}
      </div>
      <p>Stellen Sie Fragen in eigenen Worten. Die Antworten stammen ausschliesslich aus den Videotranskripten,
         Protokollen und Dokumenten – jede Aussage mit Quelle.</p>
      <ChatThread key={threadKey} chatId={chatId}
                  onCreated={(c) => { created.current = c.id; nav(`/fragen/${c.id}`, { replace: true }); }}
                  onChanged={refreshChats} />
    </div>
  );
}
