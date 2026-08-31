"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Button, Card, CardHeader, Empty, ErrorBanner, Spinner, StatCard } from "@/components/ui";

type Summary = { story_id: number; telegram_story_id: number; views: number | null; reactions: number | null; forwards: number | null; known_viewers: number; er: number | null; published_at: string | null };
type Overview = { stories: number; views: number; known_viewers: number; reactions: number; forwards: number; average_views: number; average_er: number; top_stories: Summary[] };
type RecentEvent = { type: "view" | "reaction"; story_id: number; telegram_story_id: number; user_id: number; username: string | null; first_name: string | null; last_name: string | null; reaction: string | null; occurred_at: string };

export default function AnalyticsPage() {
  const [days, setDays] = useState(3650);
  const { data, loading, error, refresh } = useFetch<Overview>((signal) => api.get(`/analytics/overview?days=${days}`, signal), [days]);
  const recent = useFetch<RecentEvent[]>((signal) => api.get(`/analytics/recent-events?limit=30`, signal), []);
  const [syncing, setSyncing] = useState(false);
  const sync = async () => { setSyncing(true); try { const accounts = await api.get<{ id: number }[]>("/accounts"); for (const account of accounts) await api.post("/analytics/sync?account_id=" + account.id); await refresh(); } finally { setSyncing(false); } };
  if (loading) return <Spinner />;
  if (error) return <ErrorBanner message={error} />;
  if (!data) return <Empty label="Нет аналитики" />;
  return <div className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h1 className="text-xl font-semibold">Статистика аккаунта</h1></div><div className="flex gap-2"><div className="flex rounded-xl border border-slate-300 p-0.5 dark:border-slate-700">{[{ value: 1, label: "Сегодня" }, { value: 7, label: "7 дней" }, { value: 30, label: "30 дней" }, { value: 90, label: "90 дней" }, { value: 3650, label: "Всё время" }].map((period) => <button key={period.value} onClick={() => setDays(period.value)} className={`rounded-lg px-3 py-1.5 text-sm ${days === period.value ? "bg-emerald-600 text-white" : "text-slate-500"}`}>{period.label}</button>)}</div><Button onClick={sync} disabled={syncing}>{syncing ? "Синхронизация…" : "Синхронизировать"}</Button></div></div>
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-6"><StatCard label="Истории" value={data.stories} /><StatCard label="Просмотры" value={data.views} accent /><StatCard label="Зрители" value={data.known_viewers} /><StatCard label="Реакции" value={data.reactions} accentKey="red" /><StatCard label="Пересылки" value={data.forwards} accentKey="sky" /><StatCard label="Средний ER" value={`${data.average_er.toFixed(2)}%`} accentKey="indigo" /></div>
    <div className="grid gap-5 lg:grid-cols-2"><Card><CardHeader title="Последние действия" subtitle="Новые просмотры и реакции на мои истории" />{recent.loading ? <div className="p-5"><Spinner /></div> : recent.data?.length ? <div className="divide-y divide-slate-100 dark:divide-slate-800">{recent.data.map((event, index) => <div key={`${event.story_id}-${event.user_id}-${event.occurred_at}-${index}`} className="flex items-center gap-3 px-5 py-3 text-sm"><span className={`flex h-8 w-8 items-center justify-center rounded-full ${event.type === "reaction" ? "bg-rose-100 dark:bg-rose-500/15" : "bg-sky-100 dark:bg-sky-500/15"}`}>{event.type === "reaction" ? "❤️" : "👁"}</span><div className="min-w-0 flex-1"><div className="truncate"><span className="font-medium">{event.username ? `@${event.username}` : [event.first_name, event.last_name].filter(Boolean).join(" ") || `User ${event.user_id}`}</span><span className="ml-2 text-slate-500">{[event.first_name, event.last_name].filter(Boolean).join(" ") || ""}</span><span className="text-slate-500"> {event.type === "reaction" ? `поставил реакцию ${event.reaction}` : "посмотрел историю"}</span> <Link className="font-medium text-emerald-600 hover:underline" href={`/analytics/stories/${event.story_id}`}>#{event.telegram_story_id}</Link></div><div className="text-xs text-slate-400">{new Date(event.occurred_at).toLocaleString("ru-RU")}</div></div></div>)}</div> : <Empty label="Новых действий пока нет" />}</Card>
    <Card><CardHeader title="Лучшие истории" subtitle={days === 3650 ? "За всё время" : `За последние ${days} дней`} />{data.top_stories.length === 0 ? <Empty label="Истории ещё не синхронизированы" /> : <div className="divide-y divide-slate-100 dark:divide-slate-800">{data.top_stories.map((story, index) => <Link href={`/analytics/stories/${story.story_id}`} key={story.story_id} className="flex items-center gap-4 px-5 py-4 hover:bg-slate-50 dark:hover:bg-slate-800/50"><span className="w-6 text-sm font-semibold text-slate-400">{index + 1}</span><span className="flex-1"><span className="font-medium">Story #{story.telegram_story_id}</span><span className="ml-3 text-xs text-slate-400">{story.published_at ? new Date(story.published_at).toLocaleString("ru-RU") : ""}</span></span><span className="text-sm text-slate-500">👁 {story.views ?? "—"}</span><span className="text-sm text-slate-500">❤️ {story.reactions ?? "—"}</span><span className="w-20 text-right text-sm font-medium text-emerald-600">{story.er == null ? "—" : `${story.er.toFixed(2)}%`}</span></Link>)}</div>}</Card></div>
  </div>;
}
