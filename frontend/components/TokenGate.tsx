"use client";
import { useState } from "react";
import { setToken } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import { Button } from "@/components/ui";

export function TokenGateContent({ onSaved }: { onSaved: () => void }) {
  const { t } = useTranslation();
  const [register, setRegister] = useState(false);
  const [form, setForm] = useState({ first_name: "", last_name: "", email: "", password: "" });
  const [error, setError] = useState("");
  const submit = async () => {
    setError("");
    try {
      const response = await fetch(`/api/user-auth/${register ? "register" : "login"}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || t("auth.authError"));
      setToken(data.token); onSaved();
    } catch (e) { setError((e as Error).message); }
  };
  const field = (key: keyof typeof form, placeholder: string) => <input value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} placeholder={placeholder} type={key === "password" ? "password" : "text"} className="mt-3 w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm dark:border-slate-700 dark:bg-slate-800" />;
  return <div className="flex min-h-screen items-center justify-center p-6"><div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-8 shadow-xl dark:border-slate-800 dark:bg-slate-900"><h1 className="text-xl font-bold">{t("auth.storyWatcher")}</h1><p className="mt-1 text-sm text-slate-500">{register ? t("auth.registration") : t("auth.loginToPanel")}</p>{register && <>{field("first_name", t("auth.firstName"))}{field("last_name", t("auth.lastName"))}</>}{field("email", t("auth.email"))}{field("password", t("auth.password"))}{error && <p className="mt-3 text-sm text-red-600">{error}</p>}<Button className="mt-5 w-full" onClick={submit}>{register ? t("auth.createAccount") : t("auth.loginButton")}</Button><button className="mt-4 w-full text-sm text-emerald-600" onClick={() => setRegister(!register)}>{register ? t("auth.hasAccount") : t("auth.noAccount")}</button></div></div>;
}
