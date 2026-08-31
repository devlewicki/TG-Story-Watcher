"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Sidebar, TopBar } from "@/components/Sidebar";
import { TokenGateContent } from "@/components/TokenGate";
import { getToken } from "@/lib/api";

const UNAUTHORIZED_EVENT = "storywatcher:unauthorized";

export function AppShell({ children }: { children: ReactNode }) {
  const [hasToken, setHasToken] = useState(false);

  useEffect(() => {
    // Initial check (after mount, so localStorage is available).
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
      <div className="pl-64">
        <TopBar />
        <main className="mx-auto max-w-6xl px-6 py-6">{children}</main>
      </div>
    </div>
  );
}