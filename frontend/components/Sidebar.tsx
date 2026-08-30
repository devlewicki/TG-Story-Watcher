"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useTheme } from "@/lib/theme";
import { clearToken } from "@/lib/api";

type IconName =
  | "dashboard"
  | "accounts"
  | "stories"
  | "queue"
  | "discovery"
  | "whitelist"
  | "blacklist"
  | "history"
  | "statistics"
  | "settings";

const ICONS: Record<IconName, ReactNode> = {
  dashboard: (
    <path d="M3 3h7v7H3V3zm11 0h7v7h-7V3zM3 14h7v7H3v-7zm11 0h7v7h-7v-7z" />
  ),
  accounts: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 3.6-7 8-7s8 3 8 7" />
    </>
  ),
  stories: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="3" />
      <circle cx="9" cy="9" r="2" />
      <path d="m21 15-3.5-3.5L7 22" />
    </>
  ),
  queue: (
    <>
      <path d="M8 6h13M8 12h13M8 18h13" />
      <circle cx="3.5" cy="6" r="1" fill="currentColor" stroke="none" />
      <circle cx="3.5" cy="12" r="1" fill="currentColor" stroke="none" />
      <circle cx="3.5" cy="18" r="1" fill="currentColor" stroke="none" />
    </>
  ),
  discovery: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
      <path d="M11 8v3l2 1" />
    </>
  ),
  whitelist: (
    <>
      <path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3z" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
  blacklist: (
    <>
      <path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3z" />
      <path d="m9.5 9.5 5 5M14.5 9.5l-5 5" />
    </>
  ),
  history: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.5 2" />
    </>
  ),
  statistics: (
    <>
      <path d="M4 20V10M10 20V4M16 20v-7M21 20H3" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34h.01a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87v.01a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1z" />
    </>
  ),
};

function Icon({ name, className = "" }: { name: IconName; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      {ICONS[name]}
    </svg>
  );
}

type NavItem = { href: string; label: string; icon: IconName };
type NavGroup = { title: string; items: NavItem[] };

const NAV_GROUPS: NavGroup[] = [
  { title: "Обзор", items: [{ href: "/", label: "Дашборд", icon: "dashboard" }] },
  { title: "Аккаунты", items: [{ href: "/accounts", label: "Аккаунты", icon: "accounts" }] },
  {
    title: "Мониторинг",
    items: [
      { href: "/stories", label: "Истории", icon: "stories" },
      { href: "/queue", label: "Очередь", icon: "queue" },
      { href: "/discovery", label: "Поиск историй", icon: "discovery" },
    ],
  },
  {
    title: "Управление",
    items: [
      { href: "/whitelist", label: "Белый список", icon: "whitelist" },
      { href: "/blacklist", label: "Чёрный список", icon: "blacklist" },
    ],
  },
  {
    title: "Аналитика",
    items: [
      { href: "/history", label: "История действий", icon: "history" },
      { href: "/statistics", label: "Статистика", icon: "statistics" },
    ],
  },
  { title: "Система", items: [{ href: "/settings", label: "Настройки", icon: "settings" }] },
];

export function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 z-20 flex w-64 flex-col border-r border-slate-200/80 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90">
      <div className="flex h-16 items-center gap-2.5 border-b border-slate-100 px-5 dark:border-slate-800">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-md shadow-emerald-600/30">
          <Icon name="stories" className="h-5 w-5" />
        </span>
        <div>
          <div className="text-[15px] font-bold tracking-tight text-slate-900 dark:text-white">
            StoryWatcher
          </div>
          <div className="text-[10px] font-medium uppercase tracking-widest text-slate-400 dark:text-slate-500">
            Telegram Stories
          </div>
        </div>
      </div>
      <nav className="flex-1 space-y-4 overflow-y-auto p-3">
        {NAV_GROUPS.map((group) => (
          <div key={group.title}>
            <div className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-widest text-slate-400 dark:text-slate-500">
              {group.title}
            </div>
            <div className="space-y-0.5">
              {group.items.map((item) => (
                <NavLink key={item.href} item={item} />
              ))}
            </div>
          </div>
        ))}
      </nav>
      <div className="border-t border-slate-100 p-3 text-[11px] text-slate-400 dark:border-slate-800 dark:text-slate-500">
        v1.0 · самохостинг
      </div>
    </aside>
  );
}

function NavLink({ item }: { item: NavItem }) {
  const pathname = usePathname();
  const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
  return (
    <Link
      href={item.href}
      className={`group relative flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm font-medium transition-all ${
        active
          ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300"
          : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
      }`}
    >
      <span
        className={`flex h-6 w-6 items-center justify-center rounded-lg transition-colors ${
          active
            ? "text-emerald-600 dark:text-emerald-400"
            : "text-slate-400 group-hover:text-slate-600 dark:text-slate-500 dark:group-hover:text-slate-300"
        }`}
      >
        <Icon name={item.icon} className="h-4 w-4" />
      </span>
      {item.label}
      {active && (
        <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-emerald-500" />
      )}
    </Link>
  );
}

const PAGE_TITLES: Record<string, string> = {
  "/": "Дашборд",
  "/accounts": "Аккаунты",
  "/stories": "Истории",
  "/queue": "Очередь",
  "/discovery": "Поиск историй",
  "/whitelist": "Белый список",
  "/blacklist": "Чёрный список",
  "/history": "История действий",
  "/statistics": "Статистика",
  "/settings": "Настройки",
};

export function TopBar() {
  const { theme, toggle } = useTheme();
  const pathname = usePathname();
  const title = PAGE_TITLES[pathname] || "StoryWatcher";

  const resetToken = () => {
    clearToken();
    window.dispatchEvent(new Event("storywatcher:unauthorized"));
  };

  return (
    <header className="sticky top-0 z-10 flex h-16 items-center justify-between border-b border-slate-200/70 bg-white/70 px-6 backdrop-blur-md dark:border-slate-800 dark:bg-slate-950/70">
      <h1 className="text-base font-semibold tracking-tight text-slate-800 dark:text-slate-100">
        {title}
      </h1>
      <div className="flex items-center gap-2">
        <button
          onClick={resetToken}
          title="Сбросить сохранённый токен"
          className="flex items-center gap-1.5 rounded-xl border border-slate-300 px-3 py-1.5 text-sm text-slate-600 transition-colors hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
            <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
            <path d="M3 3v5h5" />
          </svg>
          Сменить токен
        </button>
        <button
          onClick={toggle}
          title={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
          className="flex h-9 w-9 items-center justify-center rounded-xl border border-slate-300 text-slate-600 transition-colors hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          {theme === "dark" ? (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" className="h-4 w-4">
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4m11.4-11.4 1.4-1.4" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
              <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
            </svg>
          )}
        </button>
      </div>
    </header>
  );
}
