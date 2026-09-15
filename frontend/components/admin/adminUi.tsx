"use client";

import { useState, type ReactNode } from "react";
import { useTranslation } from "@/lib/i18n";

export function AdminCard({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900 ${className}`}>
      {children}
    </div>
  );
}

export function AdminCardHeader({ title, subtitle, right }: { title: ReactNode; subtitle?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-5 py-4 dark:border-slate-800">
      <div>
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{title}</h2>
        {subtitle ? <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{subtitle}</p> : null}
      </div>
      {right}
    </div>
  );
}

export function StatCard({ label, value, tone = "default", sub }: { label: string; value: ReactNode; tone?: "default" | "emerald" | "amber" | "red" | "sky"; sub?: ReactNode }) {
  const tones: Record<string, string> = {
    default: "text-slate-900 dark:text-slate-50",
    emerald: "text-emerald-600 dark:text-emerald-400",
    amber: "text-amber-600 dark:text-amber-400",
    red: "text-red-600 dark:text-red-400",
    sky: "text-sky-600 dark:text-sky-400",
  };
  return (
    <AdminCard className="p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</div>
      <div className={`mt-1.5 text-2xl font-bold tracking-tight ${tones[tone]}`}>{value}</div>
      {sub ? <div className="mt-1 text-xs text-slate-400">{sub}</div> : null}
    </AdminCard>
  );
}

export function HealthDot({ ok, label }: { ok: boolean | null; label?: string }) {
  const { t } = useTranslation();
  const color =
    ok === null
      ? "bg-slate-300 dark:bg-slate-600"
      : ok
        ? "bg-emerald-500"
        : "bg-red-500";
  const text =
    ok === null ? t("admin.common.unknown") : ok ? t("admin.common.healthy") : t("admin.common.down");
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {label || text}
    </span>
  );
}

export function AdminStatusBadge({ status }: { status: string }) {
  const palette: Record<string, string> = {
    ACTIVE: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400",
    VIEWED: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400",
    SUCCESS: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400",
    READY: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400",
    PROCESSING: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-400",
    RUNNING: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-400",
    PENDING: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
    WAITING_DELAY: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
    UPLOADING: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
    CREATING: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
    PAUSED: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400",
    FLOOD_WAIT: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400",
    SKIPPED: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400",
    EXPIRED: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400",
    FAILED: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-400",
    ERROR: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-400",
    AUTH_REQUIRED: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-400",
    BANNED_OR_RESTRICTED: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-400",
    CANCELLED: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
    DISCONNECTED: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
    DELETED: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
    CRITICAL: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-400",
    WARNING: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400",
    INFO: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium ${palette[status] || palette.PENDING}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-60" />
      {status.replace(/_/g, " ")}
    </span>
  );
}

export function AdminTable({ head, children }: { head: ReactNode; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead>
          <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400 dark:border-slate-800">{head}</tr>
        </thead>
        <tbody className="divide-y divide-slate-50 dark:divide-slate-800/60">{children}</tbody>
      </table>
    </div>
  );
}

export function Th({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return <th className={`px-5 py-3 font-medium ${className}`}>{children}</th>;
}

export function Td({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return <td className={`px-5 py-3 align-middle ${className}`}>{children}</td>;
}

export function AdminPagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const { t } = useTranslation();
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const pageBtn =
    "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-slate-200 transition-colors hover:bg-slate-50 disabled:opacity-40 dark:border-slate-700 dark:hover:bg-slate-800";
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 px-4 py-3 text-xs text-slate-500 dark:text-slate-400 sm:px-5">
      <span className="whitespace-nowrap">{t("admin.common.total", { n: total })}</span>
      <div className="flex items-center gap-1.5">
        <button
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
          aria-label={t("admin.common.prevPage")}
          className={pageBtn}
        >
          ←
        </button>
        <span className="whitespace-nowrap tabular-nums">
          {t("admin.common.page")} {page} {t("admin.common.of")} {pages}
        </span>
        <button
          disabled={page >= pages}
          onClick={() => onPage(page + 1)}
          aria-label={t("admin.common.nextPage")}
          className={pageBtn}
        >
          →
        </button>
      </div>
    </div>
  );
}

export function AdminSearchInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      inputMode="search"
      className="w-full max-w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none transition-colors focus:border-emerald-500 dark:border-slate-700 dark:bg-slate-800 dark:text-white sm:w-64 sm:max-w-xs"
    />
  );
}

export function AdminSelect({ value, onChange, options, className = "" }: { value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; className?: string }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none transition-colors focus:border-emerald-500 dark:border-slate-700 dark:bg-slate-800 dark:text-white ${className}`}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  danger,
  requireText,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  message?: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  requireText?: string;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [typed, setTyped] = useState("");
  if (!open) return null;
  const canConfirm = !requireText || typed === requireText;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" onClick={onClose} />
      <div className="relative max-h-[85vh] w-full max-w-md overflow-y-auto rounded-2xl border border-slate-200 bg-white p-5 shadow-xl dark:border-slate-700 dark:bg-slate-900 sm:p-6">
        <h3 className="text-base font-semibold text-slate-900 dark:text-white">{title}</h3>
        {message ? <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">{message}</p> : null}
        {requireText ? (
          <input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={requireText}
            className="mt-3 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
          />
        ) : null}
        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            {t("admin.common.cancel")}
          </button>
          <button
            disabled={!canConfirm}
            onClick={() => {
              setTyped("");
              onConfirm();
              onClose();
            }}
            className={`rounded-xl px-4 py-2 text-sm font-medium text-white transition-colors disabled:opacity-40 ${
              danger ? "bg-red-600 hover:bg-red-700" : "bg-emerald-600 hover:bg-emerald-700"
            }`}
          >
            {confirmLabel || t("admin.common.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}

export function ProgressBar({ value }: { value: number }) {
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
      <div
        className="h-full rounded-full bg-emerald-500 transition-all duration-500"
        style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
      />
    </div>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
      {message}
    </div>
  );
}

export function EmptyRow({ colSpan, label }: { colSpan: number; label: string }) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-5 py-10 text-center text-sm text-slate-400">
        {label}
      </td>
    </tr>
  );
}
