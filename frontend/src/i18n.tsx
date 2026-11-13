// UI language (DE/EN) + on-demand machine translation of archive content.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { EN } from "./i18n-en";

export type Lang = "de" | "en";

type LangCtxT = { lang: Lang; setLang: (l: Lang) => void };
export const LangCtx = createContext<LangCtxT>({ lang: "de", setLang: () => {} });

export function LangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    try { return (localStorage.getItem("ratsarchiv.lang") as Lang) || "de"; } catch { return "de"; }
  });
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try { localStorage.setItem("ratsarchiv.lang", l); } catch { /* ignore */ }
  }, []);
  useEffect(() => { document.documentElement.lang = lang; }, [lang]);
  return <LangCtx.Provider value={{ lang, setLang }}>{children}</LangCtx.Provider>;
}

export const useLang = () => useContext(LangCtx);

/** t("German UI text", {vars}) – German strings are the keys; English comes from i18n-en.ts. */
export function useT() {
  const { lang } = useLang();
  return useCallback((s: string, vars?: Record<string, string | number>) => {
    let out = lang === "en" ? (EN[s] ?? s) : s;
    if (vars) for (const [k, v] of Object.entries(vars)) out = out.split(`{${k}}`).join(String(v));
    return out;
  }, [lang]);
}

/* --------------------------------------------------------------------------- content translation */

const cache = new Map<string, string>();       // German -> English
const failed = new Set<string>();
const inflight = new Map<string, Promise<void>>();
const listeners = new Set<() => void>();
let queue: string[] = [];
let timer: number | undefined;

let running = false;

/** Process the queue one batch at a time (the LLM translates sequentially anyway), notifying after each batch. */
async function flush() {
  timer = undefined;
  if (running) return;
  running = true;
  try {
    while (queue.length) {
      const part = [...new Set(queue.splice(0, 30))].filter((t) => !cache.has(t) && !failed.has(t));
      if (!part.length) continue;
      part.forEach((src) => inflight.set(src, Promise.resolve()));
      try {
        const r = await fetch("/api/translate", {
          method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ texts: part, target: "en" }),
        });
        if (!r.ok) throw new Error(String(r.status));
        const res: { texts: string[]; ok: boolean[] } = await r.json();
        part.forEach((src, k) => (res.ok[k] ? cache.set(src, res.texts[k]) : failed.add(src)));
      } catch {
        part.forEach((src) => failed.add(src));
      } finally {
        part.forEach((src) => inflight.delete(src));
        listeners.forEach((l) => l());
      }
    }
  } finally {
    running = false;
  }
}

function request(texts: string[]) {
  const missing = texts.filter((t) => t && t.trim() && !cache.has(t) && !failed.has(t) && !inflight.has(t));
  if (!missing.length) return;
  queue.push(...missing);
  missing.forEach((src) => inflight.set(src, Promise.resolve()));
  if (timer === undefined && !running) timer = window.setTimeout(flush, 40);
}

/** Translate content strings when the UI is English. Returns a lookup + status. */
export function useContentTranslation(texts: string[], enabled = true) {
  const { lang } = useLang();
  const [, bump] = useState(0);
  const active = lang === "en" && enabled;
  const key = useMemo(() => texts.join("\u0001"), [texts]);

  useEffect(() => {
    const l = () => bump((x) => x + 1);
    listeners.add(l);
    return () => { listeners.delete(l); };
  }, []);
  useEffect(() => { if (active) request(texts); /* eslint-disable-next-line */ }, [active, key]);

  return {
    active,
    tr: (t: string) => (active ? cache.get(t) ?? t : t),
    pending: active && texts.some((t) => t && !cache.has(t) && !failed.has(t)),
    failed: (t: string) => active && failed.has(t),
  };
}

/** Inline translated text (titles, short labels). */
export function Tx({ children }: { children: string }) {
  const { tr } = useContentTranslation([children]);
  return <>{tr(children)}</>;
}

/* --------------------------------------------------------------------------- formats */

const MONTHS = {
  de: ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sept.", "Okt.", "Nov.", "Dez."],
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
};

export function fmtDateLong(iso: string | null | undefined, lang: Lang) {
  if (!iso) return "";
  const [y, mo, d] = iso.slice(0, 10).split("-").map(Number);
  return lang === "en" ? `${d} ${MONTHS.en[mo - 1]} ${y}` : `${d}. ${MONTHS.de[mo - 1]} ${y}`;
}

/** Meeting titles follow fixed patterns -> translate locally (no LLM needed for ~200 titles). */
export function meetingTitle(t: string, lang: Lang) {
  if (lang !== "en") return t;
  let m = t.match(/^(\d+)\.\s*(Demo-)?Sitzung des Gemeinderates$/);
  if (m) return `${m[2] ? "Demo meeting" : "Council meeting"} no. ${m[1]}`;
  if (/^Gemeinderatssitzung abgesagt$/i.test(t)) return "Council meeting cancelled";
  if (/^Sitzung Gemeinderat$/i.test(t)) return "Council meeting";
  return t;
}

export const DOC_TYPE_EN: Record<string, string> = {
  PR: "Minutes", TL: "Agenda", PU: "Publication", BS: "City Council decision",
  PO: "Postulate", MO: "Motion", IP: "Interpellation",
};
