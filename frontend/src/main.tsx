import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { type User, api } from "./api";
import Layout from "./components/Layout";
import Fragen from "./pages/Fragen";
import Home from "./pages/Home";
import Login from "./pages/Login";
import Planen from "./pages/Planen";
import Sitzung from "./pages/Sitzung";
import Sitzungen from "./pages/Sitzungen";
import { LangProvider } from "./i18n";
import "./styles.css";

function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);

  useEffect(() => {
    api.me().then(setUser).catch(() => setUser(null));
    const expired = () => setUser(null);
    window.addEventListener("auth:expired", expired);
    return () => window.removeEventListener("auth:expired", expired);
  }, []);

  if (user === undefined) return null;
  if (!user) return <Login onLogin={setUser} />;

  return (
    <Routes>
      <Route element={<Layout user={user} onLogout={() => setUser(null)} />}>
        <Route index element={<Home />} />
        <Route path="sitzungen" element={<Sitzungen />} />
        <Route path="sitzungen/:id" element={<Sitzung />} />
        <Route path="fragen" element={<Fragen />} />
        <Route path="fragen/:id" element={<Fragen />} />
        <Route path="planen" element={<Planen />} />
        <Route path="planen/:id" element={<Planen />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode><LangProvider><BrowserRouter><App /></BrowserRouter></LangProvider></StrictMode>,
);
