"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { AppShell } from "@/components/AppShell";

const ADMIN_PREFIX = "/admin";

/**
 * The root layout wraps every route. Admin routes must NOT be wrapped in the
 * user AppShell — they render their own AdminShell — otherwise the admin page
 * ends up inside two nested side-by-side shells (double sidebar offset,
 * double max-width centering), which shifts all admin content to the right.
 */
export function ShellGate({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isAdmin = !!pathname && pathname.startsWith(ADMIN_PREFIX);
  if (isAdmin) return <>{children}</>;
  return <AppShell>{children}</AppShell>;
}
