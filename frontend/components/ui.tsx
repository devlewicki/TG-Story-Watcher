"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { statusColor } from "@/lib/format";

export type IconName =
  | "gear"
  | "sliders"
  | "send"
  | "signal"
  | "list"
  | "shield"
  | "heart"
  | "funnel"
  | "tag"
  | "mapPin"
  | "globe"
  | "map"
  | "clock"
  | "search"
  | "crosshair"
  | "eye"
  | "check"
  | "trending"
  | "bars"
  | "refresh"
  | "trash"
  | "close"
  | "alert"
  | "chevron";

const ICON_PATHS: Record<IconName, ReactNode> = {
  gear: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34h.01a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87v.01a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1z" />
    </>
  ),
  sliders: (
    <>
      <path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3" />
      <path d="M1 14h6M9 8h6M17 16h6" />
    </>
  ),
  send: <path d="m22 2-7 20-4-9-9-4 20-7zM22 2 11 13" />,
  signal: (
    <>
      <path d="M5 12.5a10 10 0 0 1 14 0M8.5 15.5a5.5 5.5 0 0 1 7 0" />
      <circle cx="12" cy="18" r="1.5" />
    </>
  ),
  list: (
    <>
      <path d="M8 6h13M8 12h13M8 18h13" />
      <path d="M3.5 6h.01M3.5 12h.01M3.5 18h.01" />
    </>
  ),
  shield: <path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3z" />,
  heart: <path d="M12 21C7 16.5 2.5 13 2.5 8.8 2.5 6 4.6 4 7.2 4c1.8 0 3.4 1 4.8 2.6C13.4 5 15 4 16.8 4c2.6 0 4.7 2 4.7 4.8 0 4.2-4.5 7.7-9.5 12.2z" />,
  funnel: <path d="M4 5h16l-6 7v6l-4 2v-8L4 5z" />,
  tag: (
    <>
      <path d="M20.6 13.4 12 22 2 12V2h10l8.6 8.6a2 2 0 0 1 0 2.8z" />
      <circle cx="7" cy="7" r="1.5" />
    </>
  ),
  mapPin: (
    <>
      <path d="M12 21s7-7.8 7-14a7 7 0 1 0-14 0c0 6.2 7 14 7 14z" />
      <circle cx="12" cy="7" r="3" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18" />
    </>
  ),
  map: (
    <>
      <path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2z" />
      <path d="M9 4v14M15 6v14" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 3" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </>
  ),
  crosshair: (
    <>
      <circle cx="12" cy="12" r="3.5" />
      <path d="M12 2v3m0 14v3M2 12h3m14 0h3M5 5l1.5 1.5M18 18l1.5 1.5M19 5l-1.5 1.5M6 18l-1.5 1.5" />
    </>
  ),
  eye: (
    <>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  check: <path d="m4 12 5 5L20 7" />,
  trending: (
    <>
      <path d="m3 17 6-6 4 4 8-8" />
      <path d="M15 7h6v6" />
    </>
  ),
  bars: <path d="M4 20V10M10 20V4M16 20v-7M21 20H3" />,
  refresh: (
    <>
      <path d="M20 11a8 8 0 1 0-2 5.3" />
      <path d="M20 4v7h-7" />
    </>
  ),
  trash: (
    <>
      <path d="M3 6h18M8 6V4h8v2m1 0-1 14H8L7 6" />
    </>
  ),
  close: <path d="M6 6l12 12M18 6L6 18" />,
  alert: (
    <>
      <path d="M12 3 2 20h20L12 3z" />
      <path d="M12 10v4" />
      <path d="M12 17.5h.01" strokeWidth="2.6" />
    </>
  ),
  chevron: <path d="m6 9 6 6 6-6" />,
};

export function Icon({
  name,
  className = "h-5 w-5",
}: {
  name: IconName;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {ICON_PATHS[name]}
    </svg>
  );
}

export function PageHeader({
  title,
  subtitle,
  right,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-50">
          {title}
        </h1>
        {subtitle ? (
          <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">{subtitle}</div>
        ) : null}
      </div>
      {right}
    </div>
  );
}

export function PageLoading({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-20">
      <Spinner className="h-7 w-7" />
      {label ? <span className="text-sm text-slate-400 dark:text-slate-500">{label}</span> : null}
    </div>
  );
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  className = "",
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: ReactNode; title?: string }[];
  className?: string;
}) {
  return (
    <div
      className={`inline-flex max-w-full flex-wrap items-center rounded-xl border border-slate-300 bg-white p-0.5 dark:border-slate-700 dark:bg-slate-800/60 ${className}`}
    >
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          title={o.title}
          onClick={() => onChange(o.value)}
          className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
            value === o.value
              ? "bg-emerald-600 text-white shadow-sm"
              : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function IconButton({
  label,
  onClick,
  disabled,
  className = "",
  children,
}: {
  label: string;
  onClick?: () => void;
  disabled?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:cursor-not-allowed disabled:opacity-40 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200 ${className}`}
    >
      {children}
    </button>
  );
}

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-sm shadow-slate-200/50 transition-shadow hover:shadow-md hover:shadow-slate-200/60 dark:border-slate-800 dark:bg-slate-900 dark:shadow-none dark:hover:shadow-lg dark:hover:shadow-black/20 ${className}`}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  right,
}: {
  title: ReactNode;
  subtitle?: string;
  right?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4 dark:border-slate-800">
      <div>
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{title}</h2>
        {subtitle && (
          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>
        )}
      </div>
      {right}
    </div>
  );
}

const STAT_ACCENTS: Record<string, string> = {
  default: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  emerald: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400",
  sky: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-400",
  amber: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400",
  red: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-400",
  indigo: "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-400",
};

export function StatCard({
  label,
  value,
  accent = false,
  icon,
  accentKey = "emerald",
}: {
  label: string;
  value: ReactNode;
  accent?: boolean;
  icon?: ReactNode;
  accentKey?: keyof typeof STAT_ACCENTS;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
            {label}
          </div>
          <div
            className={`mt-1.5 text-2xl font-bold tracking-tight ${
              accent
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-slate-900 dark:text-slate-50"
            }`}
          >
            {value}
          </div>
        </div>
        {icon && (
          <span
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${STAT_ACCENTS[accentKey]}`}
          >
            {icon}
          </span>
        )}
      </div>
    </Card>
  );
}

export function Badge({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${statusColor(
        status
      )}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-60" />
      {status.replace(/_/g, " ")}
    </span>
  );
}

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-emerald-600 text-white shadow-sm shadow-emerald-600/30 hover:bg-emerald-700 active:scale-[0.98] disabled:bg-slate-300 dark:disabled:bg-slate-700",
  secondary:
    "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 hover:border-slate-400 active:scale-[0.98] dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700",
  danger:
    "bg-red-600 text-white shadow-sm shadow-red-600/30 hover:bg-red-700 active:scale-[0.98] disabled:bg-slate-300",
  ghost:
    "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-100",
};

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-1.5 rounded-xl px-3.5 py-2 text-sm font-medium transition-all disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
      {...props}
    />
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      className={`inline-block h-5 w-5 animate-spin rounded-full border-2 border-slate-300 border-t-emerald-500 dark:border-slate-600 dark:border-t-emerald-400 ${className}`}
    />
  );
}

export function Empty({ label }: { label: string }) {
  return (
    <div className="px-4 py-12 text-center text-sm text-slate-500 dark:text-slate-400">
      {label}
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

const AVATAR_GRADIENTS = [
  "from-emerald-500 to-teal-600",
  "from-sky-500 to-indigo-600",
  "from-rose-500 to-pink-600",
  "from-amber-500 to-orange-600",
  "from-violet-500 to-purple-600",
];

export function Avatar({
  name,
  className = "h-9 w-9 text-sm",
}: {
  name: string;
  className?: string;
}) {
  const initial = (name || "?").trim().charAt(0).toUpperCase() || "?";
  const idx = ((name || "?").charCodeAt(0) || 0) % AVATAR_GRADIENTS.length;
  return (
    <span
      className={`inline-flex shrink-0 select-none items-center justify-center rounded-full bg-gradient-to-br font-semibold text-white ${AVATAR_GRADIENTS[idx]} ${className}`}
    >
      {initial}
    </span>
  );
}

export function Switch({
  checked,
  onChange,
  disabled = false,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
        checked ? "bg-emerald-600" : "bg-slate-300 dark:bg-slate-700"
      }`}
    >
      <span
        className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${
          checked ? "translate-x-[22px]" : "translate-x-0.5"
        }`}
      />
    </button>
  );
}
