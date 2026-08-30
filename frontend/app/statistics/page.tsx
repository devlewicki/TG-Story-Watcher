"use client";

import { useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Card, CardHeader, Empty, ErrorBanner, Spinner, StatCard } from "@/components/ui";

type Stats = {
  period_days: number;
  views_total: number;
  likes_total: number;
  skipped_total: number;
  errors_total: number;
  stories_found: number;
  views_by_day: { day: string; count: number }[];
  views_by_hour: { hour: number; count: number }[];
  views_by_source: Record<string, number>;
  stories_by_source: Record<string, number>;
  queue_by_status: Record<string, number>;
  activity_by_type: Record<string, number>;
};

const PIE_COLORS = [
  "#10b981",
  "#0ea5e9",
  "#6366f1",
  "#f59e0b",
  "#f43f5e",
  "#8b5cf6",
  "#14b8a6",
  "#f97316",
  "#84cc16",
  "#e11d48",
];

const ACTIVITY_LABELS: Record<string, string> = {
  story_viewed: "Просмотрено",
  story_liked: "Лайков",
  story_queued: "В очередь",
  story_skipped: "Отфильтровано",
  fetch_available: "Синхронизация",
  discovery_hashtag: "Поиск #",
  discovery_geo: "Поиск по местам",
  discovery_error: "Ошибки поиска",
  api_error: "Ошибки API",
  worker_error: "Ошибки worker",
};

const SOURCE_LABELS: Record<string, string> = {
  monitor: "Лента аккаунта",
  "discovery:geo": "По месту",
};

const QUEUE_STATUS_COLORS: Record<string, string> = {
  PENDING: "bg-sky-500",
  WAITING_DELAY: "bg-indigo-500",
  PROCESSING: "bg-sky-400",
  VIEWED: "bg-emerald-500",
  FAILED: "bg-red-500",
  SKIPPED: "bg-slate-400",
  EXPIRED: "bg-slate-400",
  CANCELLED: "bg-slate-400",
};

const iconProps = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  className: "h-5 w-5",
};

const AXIS_TICK = { fontSize: 11, fill: "#94a3b8" };

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const v = payload[0];
  return (
    <div className="rounded-xl border border-slate-200 bg-white/95 px-3 py-2 text-xs shadow-lg backdrop-blur dark:border-slate-700 dark:bg-slate-900/95">
      <div className="mb-0.5 font-medium text-slate-500 dark:text-slate-400">
        {label ?? v.name}
      </div>
      <div className="text-sm font-semibold text-slate-900 dark:text-slate-50">{v.value}</div>
    </div>
  );
}

export default function StatisticsPage() {
  const [days, setDays] = useState(7);
  const { data, loading, error } = useFetch<Stats>(
    (s) => api.get<Stats>(`/stats?days=${days}`, s),
    [days]
  );

  if (loading) return <Spinner />;
  if (error) return <ErrorBanner message={error} />;
  if (!data) return <Empty label="Нет статистики" />;

  const dayData = data.views_by_day.map((d) => ({
    label: new Date(d.day).toLocaleDateString("ru-RU", { day: "numeric", month: "short" }),
    count: d.count,
  }));
  const hourData = data.views_by_hour.map((h) => ({
    label: `${String(h.hour).padStart(2, "0")}:00`,
    count: h.count,
  }));
  const maxHour = Math.max(...hourData.map((h) => h.count), 0);
  const sourceData = Object.entries(data.views_by_source)
    .map(([k, v]) => ({ name: SOURCE_LABELS[k] || k, value: v }))
    .sort((a, b) => b.value - a.value);
  const sourceTotal = sourceData.reduce((s, x) => s + x.value, 0) || 1;
  const activityData = Object.entries(data.activity_by_type)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([k, v]) => ({ name: ACTIVITY_LABELS[k] || k.replace(/_/g, " "), count: v }));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Статистика</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Наши действия за последние {days} дн
          </p>
        </div>
        <div className="flex rounded-xl border border-slate-300 p-0.5 dark:border-slate-700">
          {[1, 7, 14, 30].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                days === d
                  ? "bg-emerald-600 text-white shadow-sm"
                  : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100"
              }`}
            >
              {d} дн
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <StatCard label="Просмотры" value={data.views_total} accent icon={<EyeIcon />} />
        <StatCard label="Лайки" value={data.likes_total} icon={<HeartIcon />} accentKey="red" />
        <StatCard label="Найдено историй" value={data.stories_found} icon={<SearchIcon />} accentKey="sky" />
        <StatCard label="Отфильтровано" value={data.skipped_total} icon={<FilterIcon />} accentKey="amber" />
        <StatCard label="Ошибки" value={data.errors_total} icon={<AlertIcon />} accentKey={data.errors_total > 0 ? "red" : "default"} />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title="Просмотры по дням" subtitle={`За последние ${days} дн`} />
          <div className="p-4 pt-3">
            <ResponsiveContainer width="100%" height={230}>
              <AreaChart data={dayData} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                <defs>
                  <linearGradient id="gradDay" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#10b981" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#10b981" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#94a3b8" strokeOpacity={0.15} vertical={false} />
                <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={36} allowDecimals={false} />
                <Tooltip content={<ChartTooltip />} cursor={{ stroke: "#94a3b8", strokeOpacity: 0.3 }} />
                <Area
                  type="monotone"
                  dataKey="count"
                  stroke="#10b981"
                  strokeWidth={2.5}
                  fill="url(#gradDay)"
                  activeDot={{ r: 4, strokeWidth: 2 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card>
          <CardHeader title="Активность" subtitle="Что делали за период" />
          {activityData.length === 0 ? (
            <Empty label="Нет данных" />
          ) : (
            <div className="p-4 pt-3">
              <ResponsiveContainer width="100%" height={230}>
                <BarChart data={activityData} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 0 }}>
                  <defs>
                    <linearGradient id="gradAct" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor="#10b981" />
                      <stop offset="100%" stopColor="#34d399" />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#94a3b8" strokeOpacity={0.15} horizontal={false} />
                  <XAxis type="number" tick={AXIS_TICK} tickLine={false} axisLine={false} allowDecimals={false} />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={130}
                    tick={{ fontSize: 12, fill: "#64748b" }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(148,163,184,0.08)" }} />
                  <Bar dataKey="count" radius={[0, 6, 6, 0]} barSize={16}>
                    {activityData.map((a, i) => (
                      <Cell
                        key={i}
                        fill={a.name.toLowerCase().includes("ошибк") ? "#f43f5e" : "url(#gradAct)"}
                        fillOpacity={a.name.toLowerCase().includes("ошибк") ? 1 : 0.9}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title="Просмотры по часам" subtitle="Распределение за период (UTC)" />
          <div className="p-4 pt-3">
            <ResponsiveContainer width="100%" height={230}>
              <BarChart data={hourData} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#94a3b8" strokeOpacity={0.15} vertical={false} />
                <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={false} interval={3} />
                <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={36} allowDecimals={false} />
                <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(148,163,184,0.08)" }} />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {hourData.map((h, i) => (
                    <Cell
                      key={i}
                      fill={h.count === maxHour && maxHour > 0 ? "#10b981" : "#0ea5e9"}
                      fillOpacity={h.count === maxHour && maxHour > 0 ? 1 : 0.7}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card>
          <CardHeader title="Источники просмотров" subtitle="Откуда взяты истории" />
          {sourceData.length === 0 ? (
            <Empty label="Нет просмотров" />
          ) : (
            <div className="flex flex-col items-center gap-4 p-5 sm:flex-row sm:justify-center">
              <div className="relative h-48 w-48 shrink-0">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Tooltip content={<ChartTooltip />} />
                    <Pie
                      data={sourceData}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={62}
                      outerRadius={88}
                      paddingAngle={2}
                      strokeWidth={0}
                    >
                      {sourceData.map((_, i) => (
                        <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                  <span className="text-2xl font-bold text-slate-900 dark:text-slate-50">
                    {sourceTotal}
                  </span>
                  <span className="text-xs text-slate-400">просмотров</span>
                </div>
              </div>
              <ul className="w-full space-y-1.5 sm:max-w-xs">
                {sourceData.map((s, i) => (
                  <li key={s.name} className="flex items-center gap-2 text-sm">
                    <span
                      className="h-2.5 w-2.5 shrink-0 rounded-full"
                      style={{ background: PIE_COLORS[i % PIE_COLORS.length] }}
                    />
                    <span className="min-w-0 flex-1 truncate text-slate-600 dark:text-slate-300">
                      {s.name}
                    </span>
                    <span className="font-medium text-slate-900 dark:text-slate-50">{s.value}</span>
                    <span className="w-10 text-right text-xs text-slate-400">
                      {Math.round((s.value / sourceTotal) * 100)}%
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      </div>

      {Object.keys(data.queue_by_status).length > 0 && (
        <Card>
          <CardHeader title="Очередь сейчас" subtitle="Текущее состояние задач" />
          <div className="flex flex-wrap gap-3 p-5">
            {Object.entries(data.queue_by_status).map(([status, count]) => (
              <span
                key={status}
                className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800"
              >
                <span className={`h-2 w-2 rounded-full ${QUEUE_STATUS_COLORS[status] || "bg-slate-400"}`} />
                <span className="text-slate-600 dark:text-slate-300">{status.replace(/_/g, " ")}</span>
                <span className="font-semibold text-slate-900 dark:text-slate-50">{count}</span>
              </span>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function EyeIcon() {
  return (
    <svg viewBox="0 0 24 24" {...iconProps}>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}
function HeartIcon() {
  return (
    <svg viewBox="0 0 24 24" {...iconProps}>
      <path d="M12 21C7 16.5 2.5 13 2.5 8.8 2.5 6 4.6 4 7.2 4c1.8 0 3.4 1 4.8 2.6C13.4 5 15 4 16.8 4c2.6 0 4.7 2 4.7 4.8 0 4.2-4.5 7.7-9.5 12.2z" />
    </svg>
  );
}
function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" {...iconProps}>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  );
}
function FilterIcon() {
  return (
    <svg viewBox="0 0 24 24" {...iconProps}>
      <path d="M4 5h16l-6 7v6l-4 2v-8L4 5z" />
    </svg>
  );
}
function AlertIcon() {
  return (
    <svg viewBox="0 0 24 24" {...iconProps}>
      <path d="M12 3 2 20h20L12 3z" />
      <path d="M12 10v4" />
      <path d="M12 17.5h.01" strokeWidth="2.6" />
    </svg>
  );
}
