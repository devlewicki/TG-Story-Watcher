export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diff = Date.now() - then;
  const sec = Math.floor(diff / 1000);
  if (sec < 5) return "только что";
  if (sec < 60) return `${sec} сек назад`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} мин назад`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} ч назад`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day} дн назад`;
  const month = Math.floor(day / 30);
  return `${month} мес назад`;
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("ru-RU", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const STATUS_COLORS: Record<string, string> = {
  ACTIVE: "text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-500/10",
  PAUSED: "text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-500/10",
  AUTH_REQUIRED: "text-orange-600 dark:text-orange-400 bg-orange-50 dark:bg-orange-500/10",
  ERROR: "text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-500/10",
  FLOOD_WAIT: "text-purple-600 dark:text-purple-400 bg-purple-50 dark:bg-purple-500/10",
  DISCONNECTED: "text-slate-600 dark:text-slate-400 bg-slate-100 dark:bg-slate-500/10",
  BANNED_OR_RESTRICTED: "text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-500/10",
  PENDING: "text-sky-600 dark:text-sky-400 bg-sky-50 dark:bg-sky-500/10",
  WAITING_DELAY: "text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-500/10",
  PROCESSING: "text-sky-600 dark:text-sky-400 bg-sky-50 dark:bg-sky-500/10",
  VIEWED: "text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-500/10",
  SKIPPED: "text-slate-600 dark:text-slate-400 bg-slate-100 dark:bg-slate-500/10",
  FAILED: "text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-500/10",
  EXPIRED: "text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-500/10",
  CANCELLED: "text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-500/10",
};

export function statusColor(status: string): string {
  return STATUS_COLORS[status] || "text-slate-600 dark:text-slate-400 bg-slate-100 dark:bg-slate-500/10";
}