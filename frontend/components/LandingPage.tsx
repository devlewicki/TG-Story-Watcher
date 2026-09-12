"use client";

import { useState } from "react";
import { setToken } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import { Button, Spinner } from "@/components/ui";

type AuthMode = "login" | "register";

export function LandingPage({ onAuth }: { onAuth: () => void }) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<AuthMode>("login");
  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    email: "",
    password: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`/api/user-auth/${mode === "register" ? "register" : "login"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || t("auth.authError"));
      setToken(data.token);
      onAuth();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const update = (key: keyof typeof form, value: string) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const inputClass =
    "w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 transition-all placeholder:text-slate-400 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 dark:placeholder:text-slate-500";

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-emerald-50/30 dark:from-slate-950 dark:via-slate-950 dark:to-emerald-950/20">
      {/* Ambient glow */}
      <div className="pointer-events-none fixed inset-0 z-0">
        <div className="absolute -top-40 left-1/2 h-[600px] w-[900px] -translate-x-1/2 rounded-full bg-gradient-to-br from-emerald-400/10 via-teal-400/5 to-transparent blur-3xl" />
        <div className="absolute -bottom-40 right-0 h-[500px] w-[700px] rounded-full bg-gradient-to-tl from-indigo-400/8 via-sky-400/4 to-transparent blur-3xl" />
      </div>

      {/* Nav */}
      <header className="relative z-10">
        <nav className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
          <div className="flex items-center gap-2.5">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-lg shadow-emerald-600/30">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
                <rect x="3" y="3" width="18" height="18" rx="3" />
                <circle cx="9" cy="9" r="2" />
                <path d="m21 15-3.5-3.5L7 22" />
              </svg>
            </span>
            <div>
              <div className="text-lg font-bold tracking-tight text-slate-900 dark:text-white">
                TGStory
              </div>
              <div className="text-[10px] font-medium uppercase tracking-widest text-emerald-600/70 dark:text-emerald-400/60">
                tgstory.space
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setMode("login")}
              className={`hidden rounded-xl px-4 py-2 text-sm font-medium transition-all sm:block ${
                mode === "login"
                  ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
                  : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
              }`}
            >
              {t("common.login")}
            </button>
            <button
              onClick={() => setMode("register")}
              className={`hidden rounded-xl px-4 py-2 text-sm font-medium transition-all sm:block ${
                mode === "register"
                  ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
                  : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
              }`}
            >
              {t("common.register")}
            </button>
          </div>
        </nav>
      </header>

      {/* Hero */}
      <section className="relative z-10 mx-auto max-w-6xl px-6 pt-16 pb-20 text-center lg:pt-24 lg:pb-28">
        <div className="mx-auto max-w-3xl">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-emerald-200/60 bg-emerald-50/80 px-4 py-1.5 text-xs font-medium text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
            Автоматический просмотр Telegram Stories
          </div>
          <h1 className="text-4xl font-bold tracking-tight text-slate-900 dark:text-white sm:text-5xl lg:text-6xl">
            Смотрите истории
            <br />
            <span className="bg-gradient-to-r from-emerald-500 to-teal-500 bg-clip-text text-transparent">
              автоматически
            </span>
          </h1>
          <p className="mx-auto mt-6 max-w-xl text-lg leading-relaxed text-slate-600 dark:text-slate-400">
            Подключите Telegram-аккаунт и система будет просматривать истории ваших
            контактов, ставить лайки и находить новые истории по хештегам и геолокациям.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
            <Button
              variant="primary"
              className="!px-6 !py-2.5 !text-base !rounded-xl shadow-lg shadow-emerald-600/25"
              onClick={() => setMode("register")}
            >
              Начать бесплатно
            </Button>
            <a
              href="#features"
              className="inline-flex items-center gap-2 rounded-xl px-5 py-2.5 text-sm font-medium text-slate-600 transition-colors hover:text-slate-900 dark:text-slate-400 dark:hover:text-white"
            >
              Узнать больше
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
                <path d="m6 9 6 6 6-6" />
              </svg>
            </a>
          </div>
        </div>

        {/* Auth Card */}
        <div className="mx-auto mt-16 max-w-md lg:mt-20">
          <div className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white/80 shadow-2xl shadow-slate-200/50 backdrop-blur-xl dark:border-slate-800 dark:bg-slate-900/80 dark:shadow-black/40">
            {/* Tabs */}
            <div className="flex border-b border-slate-100 dark:border-slate-800">
              <button
                onClick={() => { setMode("login"); setError(""); }}
                className={`flex-1 py-3.5 text-sm font-medium transition-colors ${
                  mode === "login"
                    ? "text-emerald-600 border-b-2 border-emerald-500 dark:text-emerald-400"
                    : "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
                }`}
              >
                {t("common.login")}
              </button>
              <button
                onClick={() => { setMode("register"); setError(""); }}
                className={`flex-1 py-3.5 text-sm font-medium transition-colors ${
                  mode === "register"
                    ? "text-emerald-600 border-b-2 border-emerald-500 dark:text-emerald-400"
                    : "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
                }`}
              >
                {t("common.register")}
              </button>
            </div>

            {/* Form */}
            <div className="p-6">
              {mode === "register" && (
                <div className="mb-4 grid grid-cols-2 gap-3">
                  <input
                    value={form.first_name}
                    onChange={(e) => update("first_name", e.target.value)}
                    placeholder={t("auth.firstName")}
                    className={inputClass}
                  />
                  <input
                    value={form.last_name}
                    onChange={(e) => update("last_name", e.target.value)}
                    placeholder={t("auth.lastName")}
                    className={inputClass}
                  />
                </div>
              )}
              <input
                value={form.email}
                onChange={(e) => update("email", e.target.value)}
                placeholder={t("auth.email")}
                type="email"
                className={`mb-3 ${inputClass}`}
              />
              <input
                value={form.password}
                onChange={(e) => update("password", e.target.value)}
                placeholder={t("auth.password")}
                type="password"
                className={`${inputClass} ${
                  mode === "register" ? "" : ""
                }`}
              />
              {mode === "register" && (
                <p className="mt-2 text-xs text-slate-400 dark:text-slate-500">
                  Минимум 8 символов
                </p>
              )}

              {error && (
                <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
                  {error}
                </div>
              )}

              <button
                onClick={submit}
                disabled={loading}
                className="mt-5 flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-emerald-600/30 transition-all hover:bg-emerald-700 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading && <Spinner className="h-4 w-4 !border-white/30 !border-t-white" />}
                {mode === "register" ? t("auth.createAccount") : t("auth.loginButton")}
              </button>

              {/* Mobile toggle */}
              <p className="mt-4 text-center text-sm text-slate-500 dark:text-slate-400 sm:hidden">
                {mode === "login" ? (
                  <button onClick={() => setMode("register")} className="text-emerald-600 hover:underline dark:text-emerald-400">
                    {t("auth.noAccount")}
                  </button>
                ) : (
                  <button onClick={() => setMode("login")} className="text-emerald-600 hover:underline dark:text-emerald-400">
                    {t("auth.hasAccount")}
                  </button>
                )}
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="relative z-10 mx-auto max-w-6xl px-6 py-20">
        <div className="text-center">
          <h2 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white sm:text-3xl">
            Всё для автоматизации
          </h2>
          <p className="mx-auto mt-3 max-w-lg text-slate-500 dark:text-slate-400">
            Мощные инструменты для работы с Telegram Stories
          </p>
        </div>
        <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          <FeatureCard
            icon={
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6">
                <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
            }
            title="Автопросмотр"
            desc="Система просматривает истории ваших контактов, имитируя реальную активность"
          />
          <FeatureCard
            icon={
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6">
                <path d="M12 21C7 16.5 2.5 13 2.5 8.8 2.5 6 4.6 4 7.2 4c1.8 0 3.4 1 4.8 2.6C13.4 5 15 4 16.8 4c2.6 0 4.7 2 4.7 4.8 0 4.2-4.5 7.7-9.5 12.2z" />
              </svg>
            }
            title="Автолайк"
            desc="Автоматическая реакция на просмотренные истории — выберите свой эмодзи"
          />
          <FeatureCard
            icon={
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6">
                <circle cx="11" cy="11" r="7" />
                <path d="m20 20-3.5-3.5M11 8v3l2 1" />
              </svg>
            }
            title="Поиск историй"
            desc="Находим новые истории по хештегам и геолокациям, автоматически добавляем в очередь"
          />
          <FeatureCard
            icon={
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6">
                <path d="M12 21s7-7.8 7-14a7 7 0 1 0-14 0c0 6.2 7 14 7 14z" />
                <circle cx="12" cy="7" r="3" />
              </svg>
            }
            title="Геолокация"
            desc="Ищем истории по местоположению на карте — находите интересные точки и города"
          />
          <FeatureCard
            icon={
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6">
                <path d="M4 20V10M10 20V4M16 20v-7M21 20H3" />
              </svg>
            }
            title="Аналитика"
            desc="Подробная статистика просмотров, графики активности и отчётность"
          />
          <FeatureCard
            icon={
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6">
                <path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3z" />
              </svg>
            }
            title="Безопасность"
            desc="Белый и чёрный список, лимиты, защита от блокировки Telegram"
          />
        </div>
      </section>

      {/* Footer */}
      <footer className="relative z-10 border-t border-slate-200/60 dark:border-slate-800/60">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
          <div className="text-xs text-slate-400 dark:text-slate-500">
            © 2024 TGStory. tgstory.space
          </div>
          <div className="text-xs text-slate-400 dark:text-slate-500">
            v1.0
          </div>
        </div>
      </footer>
    </div>
  );
}

function FeatureCard({
  icon,
  title,
  desc,
}: {
  icon: React.ReactNode;
  title: string;
  desc: string;
}) {
  return (
    <div className="group rounded-2xl border border-slate-200/80 bg-white/60 p-6 shadow-sm backdrop-blur-sm transition-all hover:border-emerald-200 hover:shadow-md hover:shadow-emerald-100/50 dark:border-slate-800 dark:bg-slate-900/60 dark:hover:border-emerald-500/20 dark:hover:shadow-emerald-500/5">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-50 text-emerald-600 transition-colors group-hover:bg-emerald-100 dark:bg-emerald-500/10 dark:text-emerald-400 dark:group-hover:bg-emerald-500/15">
        {icon}
      </div>
      <h3 className="text-base font-semibold text-slate-900 dark:text-white">
        {title}
      </h3>
      <p className="mt-2 text-sm leading-relaxed text-slate-500 dark:text-slate-400">
        {desc}
      </p>
    </div>
  );
}
