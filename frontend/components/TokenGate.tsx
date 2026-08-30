"use client";

import { useEffect, useState } from "react";
import { getToken, setToken } from "@/lib/api";
import { Button } from "@/components/ui";

export function TokenGateContent({ onSaved }: { onSaved: () => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setValue(getToken() ?? "");
  }, []);

  const save = async () => {
    setError("");
    if (!value.trim()) {
      setError("Введите API-токен.");
      return;
    }
    setSaving(true);
    setToken(value.trim());
    window.dispatchEvent(new Event("storywatcher:token-saved"));
    setSaving(false);
    onSaved();
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden p-6">
      <div className="pointer-events-none absolute -top-32 left-1/2 h-72 w-[600px] -translate-x-1/2 rounded-full bg-emerald-500/15 blur-3xl dark:bg-emerald-500/20" />
      <div className="pointer-events-none absolute -bottom-40 right-0 h-72 w-[500px] rounded-full bg-indigo-500/10 blur-3xl dark:bg-indigo-500/15" />
      <div className="relative w-full max-w-md rounded-2xl border border-slate-200/80 bg-white/90 p-8 shadow-xl shadow-slate-200/60 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90 dark:shadow-black/30">
        <div className="mb-5 flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-lg shadow-emerald-600/30">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6">
              <rect x="3" y="3" width="18" height="18" rx="4" />
              <circle cx="9" cy="9" r="2" />
              <path d="m21 15-3.5-3.5L7 22" />
            </svg>
          </span>
          <div>
            <h1 className="text-xl font-bold tracking-tight text-slate-900 dark:text-slate-50">
              StoryWatcher
            </h1>
            <p className="text-xs text-slate-500 dark:text-slate-400">Панель мониторинга Telegram Stories</p>
          </div>
        </div>
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Введите API-токен, заданный на бэкенде (
          <code className="font-mono text-xs">STORYWATCHER_API_TOKEN</code>), чтобы открыть панель.
        </p>
        <input
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && save()}
          placeholder="API-токен"
          autoFocus
          className="mt-4 w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-900 transition-colors focus:border-emerald-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
        />
        {error && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
        <Button className="mt-5 w-full" onClick={save} disabled={saving}>
          {saving ? "Проверка…" : "Войти в панель"}
        </Button>
        <p className="mt-4 text-center text-xs text-slate-400 dark:text-slate-500">
          Токен по умолчанию: <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono dark:bg-slate-800">storywatcher</code>
        </p>
      </div>
    </div>
  );
}
