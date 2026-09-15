"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import {
  adminApi,
  clearAdminToken,
  getAdminToken,
  type AdminInfo,
} from "@/lib/adminApi";
import { useTheme } from "@/lib/theme";
import {
  SHELL_CONTENT_OFFSET_CLASSES,
  SHELL_MAIN_CLASSES,
  SHELL_TOPBAR_CLASSES,
} from "@/components/shellLayout";
import { useTranslation } from "@/lib/i18n";

function AdminIcon({ name, className = "h-4 w-4" }: { name: string; className?: string }) {
  const paths: Record<string, ReactNode> = {
    dashboard: <path d="M3 3h7v7H3V3zm11 0h7v7h-7V3zM3 14h7v7H3v-7zm11 0h7v7h-7v-7z" />,
    users: <><circle cx="9" cy="8" r="3.5" /><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6" /><circle cx="17" cy="9" r="2.5" /><path d="M17 14c2.8 0 5 2.2 5 5" /></>,
    accounts: <><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7" /></>,
    stories: <><rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="9" cy="9" r="2" /><path d="m21 15-3.5-3.5L7 22" /></>,
    queue: <><path d="M8 6h13M8 12h13M8 18h13" /><circle cx="3.5" cy="6" r="1" /><circle cx="3.5" cy="12" r="1" /><circle cx="3.5" cy="18" r="1" /></>,
    analytics: <path d="M4 20V10M10 20V4M16 20v-7M21 20H3" />,
    worker: <><circle cx="12" cy="12" r="3" /><path d="M12 2v3m0 14v3M2 12h3m14 0h3M4.9 4.9l2.1 2.1m10 10 2.1 2.1M4.9 19.1 7 17m10-10 2.1-2.1" /></>,
    services: <><rect x="2" y="3" width="20" height="7" rx="2" /><rect x="2" y="14" width="20" height="7" rx="2" /><path d="M6 6.5h.01M6 17.5h.01" /></>,
    activity: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.5 2" /></>,
    errors: <><path d="M12 3 2 20h20L12 3z" /><path d="M12 10v4M12 17.5h.01" /></>,
    backups: <><path d="M12 3v10m0 0 4-4m-4 4-4-4" /><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" /></>,
    security: <path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3z" />,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34h.01a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87v.01a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1z" /></>,
    automation: <><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z" /></>,
  };
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      {paths[name]}
    </svg>
  );
}

const NAV_GROUPS: { titleKey: string; items: { href: string; labelKey: string; icon: string }[] }[] = [
  {
    titleKey: "admin.nav.dashboard",
    items: [{ href: "/admin", labelKey: "admin.nav.dashboard", icon: "dashboard" }],
  },
  {
    titleKey: "admin.nav.users",
    items: [
      { href: "/admin/users", labelKey: "admin.nav.users", icon: "users" },
      { href: "/admin/accounts", labelKey: "admin.nav.accounts", icon: "accounts" },
    ],
  },
  {
    titleKey: "admin.nav.stories",
    items: [
      { href: "/admin/stories", labelKey: "admin.nav.stories", icon: "stories" },
      { href: "/admin/queue", labelKey: "admin.nav.queue", icon: "queue" },
    ],
  },
  {
    titleKey: "admin.nav.analytics",
    items: [{ href: "/admin/analytics", labelKey: "admin.nav.analytics", icon: "analytics" }],
  },
  {
    titleKey: "admin.nav.worker",
    items: [
      { href: "/admin/worker", labelKey: "admin.nav.worker", icon: "worker" },
      { href: "/admin/services", labelKey: "admin.nav.services", icon: "services" },
    ],
  },
  {
    titleKey: "admin.nav.activity",
    items: [
      { href: "/admin/activity", labelKey: "admin.nav.activity", icon: "activity" },
      { href: "/admin/errors", labelKey: "admin.nav.errors", icon: "errors" },
    ],
  },
  {
    titleKey: "admin.nav.backups",
    items: [
      { href: "/admin/backups", labelKey: "admin.nav.backups", icon: "backups" },
      { href: "/admin/security", labelKey: "admin.nav.security", icon: "security" },
    ],
  },
  {
    titleKey: "admin.nav.settings",
    items: [{ href: "/admin/settings", labelKey: "admin.nav.settings", icon: "settings" }],
  },
];

function AdminLogin({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await adminApi.post<{ token: string }>("/admin/auth/login", { username, password });
      // imported lazily to avoid circular import concerns — direct import is fine here
      const { setAdminToken } = await import("@/lib/adminApi");
      setAdminToken(res.token);
      onDone();
    } catch (err) {
      setError((err as Error).message || t("admin.login.error"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <span className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-lg shadow-emerald-600/30">
            <AdminIcon name="security" className="h-6 w-6" />
          </span>
          <h1 className="text-lg font-semibold tracking-tight text-slate-900 dark:text-white">{t("admin.login.title")}</h1>
          <p className="mt-1 text-xs text-slate-400">{t("admin.subtitle")}</p>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-2xl border border-slate-200/80 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          {error && (
            <div className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
              {error}
            </div>
          )}
          <div>
            <label className="mb-1.5 block text-xs font-medium text-slate-600 dark:text-slate-300">{t("admin.login.username")}</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition-colors focus:border-emerald-500 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-slate-600 dark:text-slate-300">{t("admin.login.password")}</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition-colors focus:border-emerald-500 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
            />
          </div>
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-emerald-700 disabled:opacity-50"
          >
            {t("admin.login.submit")}
          </button>
          <p className="text-[11px] leading-relaxed text-slate-400">{t("admin.login.bootstrapHint")}</p>
        </form>
      </div>
    </div>
  );
}

export default function AdminLayout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { theme, toggle } = useTheme();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);
  const [authed, setAuthed] = useState(false);
  const [me, setMe] = useState<AdminInfo | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    setAuthed(!!getAdminToken());
    setReady(true);
    const onUnauthorized = () => setAuthed(false);
    window.addEventListener("storywatcher:admin-unauthorized", onUnauthorized);
    return () => window.removeEventListener("storywatcher:admin-unauthorized", onUnauthorized);
  }, []);

  // Lock body scroll while the mobile drawer is open (same UX as user shell).
  useEffect(() => {
    if (!mobileOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [mobileOpen]);

  useEffect(() => {
    if (!authed) {
      setMe(null);
      return;
    }
    adminApi
      .get<AdminInfo>("/admin/auth/me")
      .then(setMe)
      .catch(() => setAuthed(false));
  }, [authed]);

  // Login route keeps its own page (app/admin/login/page.tsx renders this layout too),
  // so we only gate when there is no token.
  if (!ready) {
    return <div className="min-h-screen" />;
  }
  if (!authed) {
    return <AdminLogin onDone={() => setAuthed(true)} />;
  }

  const active = (href: string) => (href === "/admin" ? pathname === "/admin" : pathname.startsWith(href));

  // Page title from the current /admin/<section> route; fall back to the panel
  // name instead of rendering a raw translation key.
  const section = pathname === "/admin" ? "dashboard" : pathname.split("/")[2] || "dashboard";
  const adminTitleKey = `admin.nav.${section}`;
  const adminTitle = t(adminTitleKey) !== adminTitleKey ? t(adminTitleKey) : t("admin.title");

  const nav = (
    <nav className="flex-1 space-y-4 overflow-y-auto p-3">
      {NAV_GROUPS.map((group) => (
        <div key={group.titleKey}>
          <div className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">
            {t(group.titleKey)}
          </div>
          <div className="space-y-0.5">
            {group.items.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setMobileOpen(false)}
                className={`group relative flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm font-medium transition-all ${
                  active(item.href)
                    ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-slate-100"
                }`}
              >
                <span className={`flex h-6 w-6 items-center justify-center rounded-lg ${active(item.href) ? "text-emerald-600 dark:text-emerald-400" : "text-slate-400 group-hover:text-slate-600 dark:text-slate-500 dark:group-hover:text-slate-300"}`}>
                  <AdminIcon name={item.icon} />
                </span>
                {t(item.labelKey)}
                {active(item.href) && <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-emerald-500" />}
              </Link>
            ))}
          </div>
        </div>
      ))}
    </nav>
  );

  return (
    <div className="min-h-screen">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 flex-col border-r border-slate-200/80 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90 md:flex">
        <div className="flex h-16 items-center gap-2.5 border-b border-slate-100 px-5 dark:border-slate-800">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-md shadow-emerald-600/30">
            <AdminIcon name="security" className="h-5 w-5" />
          </span>
          <div>
            <div className="text-[15px] font-bold tracking-tight text-slate-900 dark:text-white">{t("admin.title")}</div>
            <div className="text-[10px] font-medium uppercase tracking-widest text-slate-400 dark:text-slate-500">{t("admin.subtitle")}</div>
          </div>
        </div>
        {nav}
        <div className="border-t border-slate-100 p-3 dark:border-slate-800">
          <div className="flex items-center justify-between gap-2 rounded-xl px-3 py-2">
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-slate-700 dark:text-slate-200">{me?.username || "—"}</div>
              <div className="text-[11px] text-emerald-600 dark:text-emerald-400">{me ? t(`admin.roles.${me.role}`) : ""}</div>
            </div>
            <button
              onClick={() => {
                clearAdminToken();
                setAuthed(false);
              }}
              title={t("admin.common.logout")}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" /></svg>
            </button>
          </div>
          <div className="flex items-center justify-between px-3 pb-1 pt-1">
            <Link href="/" className="text-[11px] text-emerald-600 hover:underline dark:text-emerald-400">{t("admin.backToApp")}</Link>
          </div>
        </div>
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-72 flex-col border-r border-slate-200/80 bg-white/95 backdrop-blur dark:border-slate-800 dark:bg-slate-900/95">
            <div className="flex h-16 items-center justify-between border-b border-slate-100 px-5 dark:border-slate-800">
              <div className="text-[15px] font-bold tracking-tight text-slate-900 dark:text-white">{t("admin.title")}</div>
              <button onClick={() => setMobileOpen(false)} className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-5 w-5"><path d="M6 6l12 12M18 6L6 18" /></svg>
              </button>
            </div>
            {nav}
          </aside>
        </div>
      )}

      <div className="md:pl-64">
        {/* Top bar — same geometry as the user shell top bar */}
        <header className={SHELL_TOPBAR_CLASSES}>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setMobileOpen(true)}
              className="flex h-9 w-9 items-center justify-center rounded-xl border border-slate-300 text-slate-600 transition-colors hover:bg-slate-50 md:hidden dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-4 w-4"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
            </button>
            <h1 className="text-lg font-semibold tracking-tight text-slate-800 dark:text-slate-100">
              {adminTitle}
            </h1>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={toggle}
              title={theme === "dark" ? t("common.lightTheme") : t("common.darkTheme")}
              className="flex h-9 w-9 items-center justify-center rounded-xl border border-slate-300 text-slate-600 transition-colors hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              {theme === "dark" ? <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" className="h-4 w-4"><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4m11.4-11.4 1.4-1.4" /></svg> : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>}
            </button>
            <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${me?.role === "SUPER_ADMIN" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"}`}>
              {me ? t(`admin.roles.${me.role}`) : "…"}
            </span>
          </div>
        </header>
        <main className={SHELL_MAIN_CLASSES}>{children}</main>
      </div>
    </div>
  );
}
