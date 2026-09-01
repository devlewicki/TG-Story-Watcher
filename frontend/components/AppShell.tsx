"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Sidebar, TopBar } from "@/components/Sidebar";
import { TokenGateContent } from "@/components/TokenGate";
import { getToken } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";

const UNAUTHORIZED_EVENT = "storywatcher:unauthorized";

import Link from "next/link";
import { usePathname } from "next/navigation";

function useBottomNav() {
  const { t } = useTranslation();
  return [
    { href: "/", label: t("nav.dashboard"), icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5"><path d="M3 3h7v7H3V3zm11 0h7v7h-7V3zM3 14h7v7H3v-7zm11 0h7v7h-7v-7z" /></svg> },
    { href: "/stories", label: t("nav.stories"), icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5"><rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="9" cy="9" r="2" /><path d="m21 15-3.5-3.5L7 22" /></svg> },
    { href: "/discovery", label: t("nav.discovery"), icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5M11 8v3l2 1" /></svg> },
    { href: "/queue", label: t("nav.queue"), icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5"><path d="M8 6h13M8 12h13M8 18h13" /><circle cx="3.5" cy="6" r="1" fill="currentColor" stroke="none" /><circle cx="3.5" cy="12" r="1" fill="currentColor" stroke="none" /><circle cx="3.5" cy="18" r="1" fill="currentColor" stroke="none" /></svg> },
    { href: "/settings", label: t("nav.settings"), icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34h.01a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87v.01a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1z" /></svg> },
  ];
}

function BottomNav() {
  const pathname = usePathname();
  const BOTTOM_NAV = useBottomNav();
  return (
    <nav className="fixed inset-x-0 bottom-0 z-30 flex items-center justify-around border-t border-slate-200/80 bg-white/90 backdrop-blur-md dark:border-slate-800 dark:bg-slate-950/90 md:hidden" style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
      {BOTTOM_NAV.map((item) => {
        const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        return (
          <Link key={item.href} href={item.href} className={`flex flex-col items-center gap-0.5 px-3 py-2 text-[10px] font-medium transition-colors ${active ? "text-emerald-600 dark:text-emerald-400" : "text-slate-500 dark:text-slate-400"}`}>
            {item.icon}
            <span>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [hasToken, setHasToken] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (!token || !token.startsWith("user.")) {
      if (token) localStorage.removeItem("storywatcher_api_token");
      setHasToken(false);
    } else {
      setHasToken(true);
    }

    const onUnauthorized = () => setHasToken(false);
    const onTokenSaved = () => setHasToken(!!getToken());
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    window.addEventListener("storywatcher:token-saved", onTokenSaved);
    return () => {
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
      window.removeEventListener("storywatcher:token-saved", onTokenSaved);
    };
  }, []);

  if (!hasToken) {
    return <TokenGateContent onSaved={() => setHasToken(!!getToken())} />;
  }

  return (
    <div className="min-h-screen">
      <Sidebar />
      <div className="md:pl-64">
        <TopBar />
        <main className="mx-auto max-w-6xl px-4 pb-24 pt-4 sm:px-6 sm:py-6">{children}</main>
      </div>
      <BottomNav />
    </div>
  );
}
