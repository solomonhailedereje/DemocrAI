import { createContext, useContext } from "react";
import type { ItemKind, User } from "./api";

export type NewItem = { kind: ItemKind; title: string; ref?: Record<string, any>; note?: string };

export type ChatDrawerOpts = { meetingId?: string; meetingTitle?: string; question?: string; sourceTypes?: string[] };

export type AppCtx = {
  user: User;
  openSearch: (q?: string, opts?: { meetingId?: string }) => void;
  openChat: (opts?: ChatDrawerOpts) => void;
  addToProject: (item: NewItem) => void;
  toast: (msg: string, link?: { to: string; label: string }) => void;
  logout: () => void;
  /** last breadcrumb (e.g. meeting or project title) */
  setCrumbTitle: (t: string | null) => void;
};

export const Ctx = createContext<AppCtx | null>(null);

export function useApp(): AppCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useApp outside provider");
  return c;
}
