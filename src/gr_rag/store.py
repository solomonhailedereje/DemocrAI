"""SQLite storage for users, sessions, chats and projects ("Planen").

A project collects everything an employee needs for one report:
saved chat answers, searches, agenda items, documents, meetings, video
excerpts and free notes - plus the report draft itself.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  pw_hash TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chats (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL, meeting_id TEXT, created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  role TEXT NOT NULL, content TEXT NOT NULL, sources TEXT NOT NULL DEFAULT '[]',
  grounded INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'Allgemein', description TEXT NOT NULL DEFAULT '',
  report TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, title TEXT NOT NULL, ref TEXT NOT NULL DEFAULT '{}', note TEXT NOT NULL DEFAULT '',
  created TEXT NOT NULL);
"""

ITEM_KINDS = {"chat", "answer", "search", "agenda", "document", "meeting", "excerpt", "note"}
SESSION_DAYS = 14


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- passwords (stdlib scrypt)

def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
    except ValueError:
        return False
    test = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return hmac.compare_digest(test.hex(), h)


# --------------------------------------------------------------------------- store

class Store:
    def __init__(self, path: Path | str):
        self.path = str(path)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    def _one(self, sql: str, args=()) -> dict | None:
        with self._conn() as c:
            r = c.execute(sql, args).fetchone()
        return dict(r) if r else None

    def _all(self, sql: str, args=()) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def _exec(self, sql: str, args=()) -> int:
        with self._conn() as c:
            return c.execute(sql, args).lastrowid

    # ---- users & sessions
    def add_user(self, email: str, name: str, password: str) -> int:
        if len(password) < 8:
            raise ValueError("Passwort muss mindestens 8 Zeichen haben.")
        return self._exec("INSERT INTO users(email,name,pw_hash,created) VALUES(?,?,?,?)",
                          (email.strip().lower(), name.strip(), hash_password(password), now()))

    def set_password(self, email: str, password: str) -> None:
        self._exec("UPDATE users SET pw_hash=? WHERE email=?", (hash_password(password), email.strip().lower()))

    def list_users(self) -> list[dict]:
        return self._all("SELECT id,email,name,created FROM users ORDER BY id")

    def login(self, email: str, password: str) -> str | None:
        u = self._one("SELECT * FROM users WHERE email=?", (email.strip().lower(),))
        if not u or not check_password(password, u["pw_hash"]):
            return None
        token = secrets.token_urlsafe(32)
        exp = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
        self._exec("INSERT INTO sessions(token,user_id,expires) VALUES(?,?,?)", (token, u["id"], exp))
        return token

    def user_for_token(self, token: str | None) -> dict | None:
        if not token:
            return None
        return self._one("SELECT u.id,u.email,u.name FROM sessions s JOIN users u ON u.id=s.user_id "
                         "WHERE s.token=? AND s.expires>?", (token, now()))

    def logout(self, token: str) -> None:
        self._exec("DELETE FROM sessions WHERE token=?", (token,))

    # ---- chats
    def create_chat(self, user_id: int, title: str = "Neuer Chat", meeting_id: str | None = None) -> dict:
        t = now()
        cid = self._exec("INSERT INTO chats(user_id,title,meeting_id,created,updated) VALUES(?,?,?,?,?)",
                         (user_id, title, meeting_id, t, t))
        return self.get_chat(user_id, cid)

    def list_chats(self, user_id: int) -> list[dict]:
        return self._all("SELECT * FROM chats WHERE user_id=? ORDER BY updated DESC", (user_id,))

    def get_chat(self, user_id: int, chat_id: int) -> dict | None:
        chat = self._one("SELECT * FROM chats WHERE id=? AND user_id=?", (chat_id, user_id))
        if chat:
            chat["messages"] = [
                {**m, "sources": json.loads(m["sources"]), "grounded": bool(m["grounded"])}
                for m in self._all("SELECT * FROM messages WHERE chat_id=? ORDER BY id", (chat_id,))]
        return chat

    def rename_chat(self, user_id: int, chat_id: int, title: str) -> None:
        self._exec("UPDATE chats SET title=? WHERE id=? AND user_id=?", (title, chat_id, user_id))

    def delete_chat(self, user_id: int, chat_id: int) -> None:
        self._exec("DELETE FROM chats WHERE id=? AND user_id=?", (chat_id, user_id))

    def add_message(self, chat_id: int, role: str, content: str, sources: list | None = None,
                    grounded: bool = True) -> dict:
        t = now()
        mid = self._exec("INSERT INTO messages(chat_id,role,content,sources,grounded,created) VALUES(?,?,?,?,?,?)",
                         (chat_id, role, content, json.dumps(sources or [], ensure_ascii=False), int(grounded), t))
        self._exec("UPDATE chats SET updated=? WHERE id=?", (t, chat_id))
        return {"id": mid, "chat_id": chat_id, "role": role, "content": content, "sources": sources or [],
                "grounded": grounded, "created": t}

    # ---- projects
    def create_project(self, user_id: int, title: str, category: str = "Allgemein", description: str = "") -> dict:
        t = now()
        pid = self._exec("INSERT INTO projects(user_id,title,category,description,created,updated) "
                         "VALUES(?,?,?,?,?,?)", (user_id, title, category or "Allgemein", description, t, t))
        return self.get_project(user_id, pid)

    def list_projects(self, user_id: int) -> list[dict]:
        return self._all("SELECT p.id,p.title,p.category,p.description,p.created,p.updated, "
                         "(SELECT COUNT(*) FROM items i WHERE i.project_id=p.id) AS n_items "
                         "FROM projects p WHERE user_id=? ORDER BY category, updated DESC", (user_id,))

    def get_project(self, user_id: int, pid: int) -> dict | None:
        p = self._one("SELECT * FROM projects WHERE id=? AND user_id=?", (pid, user_id))
        if p:
            p["items"] = [{**i, "ref": json.loads(i["ref"])}
                          for i in self._all("SELECT * FROM items WHERE project_id=? ORDER BY id", (pid,))]
        return p

    def update_project(self, user_id: int, pid: int, **fields) -> dict | None:
        allowed = {k: v for k, v in fields.items() if k in {"title", "category", "description", "report"} and v is not None}
        if allowed:
            sets = ", ".join(f"{k}=?" for k in allowed)
            self._exec(f"UPDATE projects SET {sets}, updated=? WHERE id=? AND user_id=?",
                       (*allowed.values(), now(), pid, user_id))
        return self.get_project(user_id, pid)

    def delete_project(self, user_id: int, pid: int) -> None:
        self._exec("DELETE FROM projects WHERE id=? AND user_id=?", (pid, user_id))

    def add_item(self, user_id: int, pid: int, kind: str, title: str, ref: dict | None = None, note: str = "") -> dict | None:
        if kind not in ITEM_KINDS:
            raise ValueError(f"unknown item kind {kind}")
        if not self._one("SELECT id FROM projects WHERE id=? AND user_id=?", (pid, user_id)):
            return None
        iid = self._exec("INSERT INTO items(project_id,kind,title,ref,note,created) VALUES(?,?,?,?,?,?)",
                         (pid, kind, title, json.dumps(ref or {}, ensure_ascii=False), note, now()))
        self._exec("UPDATE projects SET updated=? WHERE id=?", (now(), pid))
        return {**self._one("SELECT * FROM items WHERE id=?", (iid,)), "ref": ref or {}}

    def update_item(self, user_id: int, pid: int, iid: int, note: str) -> None:
        if self._one("SELECT id FROM projects WHERE id=? AND user_id=?", (pid, user_id)):
            self._exec("UPDATE items SET note=? WHERE id=? AND project_id=?", (note, iid, pid))

    def delete_item(self, user_id: int, pid: int, iid: int) -> None:
        if self._one("SELECT id FROM projects WHERE id=? AND user_id=?", (pid, user_id)):
            self._exec("DELETE FROM items WHERE id=? AND project_id=?", (iid, pid))
