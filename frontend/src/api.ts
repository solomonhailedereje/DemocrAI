// Typed client for the FastAPI backend (src/gr_rag/api.py).

export type User = { id: number; email: string; name: string };

export type SourceType = "transcript" | "protokoll" | "dokument";

export type Source = {
  n?: number;
  support?: number;
  score?: number;
  similarity?: number;
  id: string;
  source_type: SourceType;
  meeting_id: string | null;
  meeting_title: string;
  date: string | null;
  text: string;
  start?: number;
  end?: number;
  label: string;
  url: string;
  doc_id?: string;
  doc_title?: string;
  page?: number;
};

export type Cited = { text: string; sources: { n: number; chunk: Source }[] };

export type Doc = {
  title: string; url: string; doc_type: string; doc_id: string;
  agenda?: string | null; has_text?: boolean; n_pages?: number | null; has_summary?: boolean;
};

export type AgendaItem = { number: string; title: string; geschaeft: string; documents: Doc[] };

export type Chapter = {
  number: string; title: string; start: number; end: number; confidence: "announced" | "estimated";
};

export type MeetingSummary = {
  generated_at: string; model: string; chapters: Chapter[];
  items: { number: string; title: string; video: Cited | null; protokoll: Cited | null }[];
  outcomes: Cited[];
};

export type MeetingListItem = {
  id: string; title: string; date: string | null; start: string | null; end: string | null;
  cancelled: boolean; youtube_id: string | null; n_agenda: number;
  has_video: boolean; has_transcript: boolean; has_protokoll: boolean; has_summary: boolean;
};

export type Meeting = MeetingListItem & {
  url: string; youtube_url: string | null; agenda: AgendaItem[]; documents: Doc[];
  summary: MeetingSummary | null;
};

export type Segment = { start: number; end: number; text: string };

export type DocSummary = {
  doc_id: string; blocks: Cited[]; pages_total: number; pages_covered: number; generated_at: string;
};

export type Message = {
  id: number; role: "user" | "assistant"; content: string; sources: Source[];
  grounded: boolean; created: string; removed?: number;
};

export type Chat = {
  id: number; title: string; meeting_id: string | null; created: string; updated: string;
  messages?: Message[];
};

export type ItemKind = "chat" | "answer" | "search" | "agenda" | "document" | "meeting" | "excerpt" | "note";

export type ProjectItem = {
  id: number; project_id: number; kind: ItemKind; title: string; ref: Record<string, any>;
  note: string; created: string;
};

export type Project = {
  id: number; title: string; category: string; description: string; report: string;
  created: string; updated: string; n_items?: number; items?: ProjectItem[];
};

export type Filters = {
  source_types?: SourceType[]; date_from?: string; date_to?: string; meeting_id?: string;
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method,
    credentials: "same-origin",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail ?? msg; } catch { /* not json */ }
    if (r.status === 401 && !url.endsWith("/login")) window.dispatchEvent(new Event("auth:expired"));
    throw new ApiError(r.status, msg);
  }
  const ct = r.headers.get("content-type") ?? "";
  return (ct.includes("json") ? r.json() : r.text()) as Promise<T>;
}

export const api = {
  me: () => req<User>("GET", "/api/auth/me"),
  login: (email: string, password: string) => req<User>("POST", "/api/auth/login", { email, password }),
  logout: () => req("POST", "/api/auth/logout"),

  meetings: () => req<MeetingListItem[]>("GET", "/api/meetings"),
  meeting: (id: string) => req<Meeting>("GET", `/api/meetings/${id}`),
  transcript: (id: string) => req<{ complete: boolean; segments: Segment[] }>("GET", `/api/meetings/${id}/transcript`),

  search: (q: string, opts: { types?: SourceType[]; meeting_id?: string; date_from?: string; date_to?: string; limit?: number } = {}) => {
    const p = new URLSearchParams({ q });
    if (opts.types?.length) p.set("types", opts.types.join(","));
    if (opts.meeting_id) p.set("meeting_id", opts.meeting_id);
    if (opts.date_from) p.set("date_from", opts.date_from);
    if (opts.date_to) p.set("date_to", opts.date_to);
    if (opts.limit) p.set("limit", String(opts.limit));
    return req<Source[]>("GET", `/api/search?${p}`);
  },

  docSummary: (docId: string) => req<DocSummary>("GET", `/api/documents/${docId}/summary`),
  makeDocSummary: (docId: string, refresh = false) =>
    req<DocSummary>("POST", `/api/documents/${docId}/summary${refresh ? "?refresh=true" : ""}`),

  chats: () => req<Chat[]>("GET", "/api/chats"),
  chat: (id: number) => req<Chat>("GET", `/api/chats/${id}`),
  createChat: (meeting_id?: string, title?: string) => req<Chat>("POST", "/api/chats", { meeting_id, title }),
  renameChat: (id: number, title: string) => req<Chat>("PATCH", `/api/chats/${id}`, { title }),
  deleteChat: (id: number) => req("DELETE", `/api/chats/${id}`),

  projects: () => req<Project[]>("GET", "/api/projects"),
  project: (id: number) => req<Project>("GET", `/api/projects/${id}`),
  createProject: (title: string, category: string, description = "") =>
    req<Project>("POST", "/api/projects", { title, category, description }),
  updateProject: (id: number, patch: Partial<Pick<Project, "title" | "category" | "description" | "report">>) =>
    req<Project>("PATCH", `/api/projects/${id}`, patch),
  deleteProject: (id: number) => req("DELETE", `/api/projects/${id}`),
  addItem: (pid: number, item: { kind: ItemKind; title: string; ref?: Record<string, any>; note?: string }) =>
    req<ProjectItem>("POST", `/api/projects/${pid}/items`, item),
  updateItem: (pid: number, iid: number, note: string) => req("PATCH", `/api/projects/${pid}/items/${iid}`, { note }),
  deleteItem: (pid: number, iid: number) => req("DELETE", `/api/projects/${pid}/items/${iid}`),
  projectFromAgenda: (meeting_id: string, number: string, category?: string) =>
    req<Project>("POST", "/api/projects/from-agenda", { meeting_id, number, category }),
  exportProject: (id: number) => req<string>("GET", `/api/projects/${id}/export`),
};

/** Stream an answer: calls onToken for raw text, resolves with the final validated message. */
export async function ask(chatId: number, content: string, filters: Filters, onToken: (t: string) => void): Promise<Message> {
  const r = await fetch(`/api/chats/${chatId}/messages`, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, filters }),
  });
  if (!r.ok || !r.body) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail ?? msg; } catch { /* ignore */ }
    throw new ApiError(r.status, msg);
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      const ev = JSON.parse(line);
      if (ev.type === "token") onToken(ev.text);
      else if (ev.type === "final") return ev.message as Message;
      else if (ev.type === "error") throw new ApiError(500, ev.message);
    }
  }
  throw new ApiError(500, "Antwort unvollständig");
}

// ---------------------------------------------------------------- helpers

export const fmtTs = (s: number) => {
  const t = Math.floor(s);
  return `${Math.floor(t / 3600)}:${String(Math.floor((t % 3600) / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
};

export const fmtDate = (iso: string | null | undefined) => {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
};

export const DOC_TYPES: Record<string, string> = {
  PR: "Protokoll", TL: "Traktandenliste", PU: "Publikation", BS: "Stadtratsbeschluss",
  PO: "Postulat", MO: "Motion", IP: "Interpellation",
};

/** Internal link for a source: transcripts open the Sitzung page at the timestamp. */
export const sourceHref = (s: Source) =>
  s.source_type === "transcript" && s.meeting_id ? `/sitzungen/${s.meeting_id}?t=${Math.floor(s.start ?? 0)}` : s.url;
