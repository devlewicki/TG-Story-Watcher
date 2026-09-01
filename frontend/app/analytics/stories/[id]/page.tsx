"use client";

import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Card, CardHeader, Empty, ErrorBanner, Spinner, StatCard } from "@/components/ui";

type Story = { story_id: number; telegram_story_id: number; views: number | null; reactions: number | null; forwards: number | null; known_viewers: number; er: number | null; reaction_breakdown: Record<string, number> };
type Point = { collected_at: string; views: number | null; reactions: number | null; forwards: number | null };
type Viewer = { telegram_user_id: number; username: string | null; first_name: string | null; last_name: string | null; viewed_at: string | null; reaction: string | null };
export default function StoryAnalyticsPage() {
  const { id } = useParams<{ id: string }>();
  const story = useFetch<Story>((s) => api.get(`/analytics/stories/${id}`, s), [id]);
  const points = useFetch<Point[]>((s) => api.get(`/analytics/stories/${id}/views`, s), [id]);
  const viewers = useFetch<Viewer[]>((s) => api.get(`/analytics/stories/${id}/viewers`, s), [id]);
  if (story.loading) return <Spinner />;
  if (story.error) return <ErrorBanner message={story.error} />;
  if (!story.data) return <Empty label="История не найдена" />;
  const s = story.data;
  return <div className="space-y-5"><div><h1 className="text-xl font-semibold">История #{s.telegram_story_id}</h1><p className="text-sm text-slate-500">Исторические значения статистики</p></div><div className="grid grid-cols-2 gap-4 lg:grid-cols-5"><StatCard label="Просмотры" value={s.views ?? "—"} accent /><StatCard label="Известные зрители" value={s.known_viewers} /><StatCard label="Реакции" value={s.reactions ?? "—"} accentKey="red" /><StatCard label="Пересылки" value={s.forwards ?? "—"} accentKey="sky" /><StatCard label="ER" value={s.er == null ? "—" : `${s.er.toFixed(2)}%`} accentKey="indigo" /></div><Card><CardHeader title="Снимки статистики" />{points.loading ? <Spinner /> : points.data?.length ? <div className="max-h-72 overflow-auto"><table className="w-full text-left text-sm"><thead><tr className="text-slate-400"><th className="px-5 py-3">Время</th><th>Просмотры</th><th>Реакции</th><th>Пересылки</th></tr></thead><tbody>{points.data.map((p, i) => <tr key={i} className="border-t border-slate-100 dark:border-slate-800"><td className="px-5 py-2">{new Date(p.collected_at).toLocaleString("ru-RU")}</td><td>{p.views ?? "—"}</td><td>{p.reactions ?? "—"}</td><td>{p.forwards ?? "—"}</td></tr>)}</tbody></table></div> : <Empty label="Снимков пока нет" />}</Card><div className="grid gap-5 lg:grid-cols-2"><Card><CardHeader title="Реакции" />{Object.entries(s.reaction_breakdown).length ? <div className="space-y-2 p-5">{Object.entries(s.reaction_breakdown).map(([reaction, count]) => <div className="flex justify-between" key={reaction}><span>{reaction}</span><b>{count}</b></div>)}</div> : <Empty label="Реакций нет" />}</Card><Card><CardHeader title="Зрители" subtitle={`${s.known_viewers} известных`} />{viewers.loading ? <Spinner /> : viewers.data?.length ? <div className="max-h-64 overflow-auto"><div className="divide-y divide-slate-100 dark:divide-slate-800">{viewers.data.map((v) => <div className="flex justify-between px-5 py-3 text-sm" key={v.telegram_user_id}><span>{v.username ? `@${v.username}` : v.first_name || v.telegram_user_id}</span><span>{v.reaction || "—"}</span></div>)}</div></div> : <Empty label="Данные зрителей недоступны" />}</Card></div></div>;
}
