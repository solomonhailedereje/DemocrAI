import { useState } from "react";
import { type User, api } from "../api";
import * as I from "../components/Icons";

export default function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try { onLogin(await api.login(email, pw)); } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <div className="login-wrap">
      <header className="header"><I.Wordmark /></header>
      <nav className="crumbs"><span className="current">Anmeldung</span></nav>
      <form className="login-card stack" onSubmit={submit}>
        <h1>Login</h1>
        <p>Bitte geben Sie Ihre E-Mail-Adresse und Ihr Passwort ein.</p>
        <input className="input" type="email" autoComplete="username" placeholder="E-Mail" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input className="input" type="password" autoComplete="current-password" placeholder="Passwort" value={pw} onChange={(e) => setPw(e.target.value)} required />
        {err && <div className="notice error">{err}</div>}
        <button className="btn primary" disabled={busy}>Anmelden</button>
        <p className="muted small">Konten für Mitarbeitende werden von der Administration angelegt (<code>gr-rag add-user</code>).
          DemocrAI ist ein Forschungsprojekt, kein offizielles Angebot der Stadt Dübendorf.</p>
      </form>
    </div>
  );
}
