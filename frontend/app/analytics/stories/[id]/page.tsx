"use client";

import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { useTranslation, useLocale } from "@/lib/i18n";
import { Card, CardHeader, Empty, ErrorBanner, Icon, PageHeader, PageLoading, Spinner, StatCard } from "@/components/ui";

type Story = { story_id: number; telegram_story_id: number; views: number | null; reactions: number | null; forwards: number | null; known_viewers: number; er: number | null; reaction_breakdown: Record<string, number> | null };
type Point = { collected_at: string; views: number | null; reactions: number | null; forwards: number | null };
type Viewer = { telegram_user_id: number; username: string | null; first_name: string | null; last_name: string | null; viewed_at: string | null; reaction: string | null };

export default function StoryAnalyticsPage() {
  const { id } = useParams<{ id: string }>();
  const { t } = useTranslation();
  const locale = useLocale();
  const story = useFetch<Story>((s) => api.get(`/analytics/stories/${id}`, s), [id]);
  const points = useFetch<Point[]>((s) => api.get(`/analytics/stories/${id}/views`, s), [id]);
  const viewers = useFetch<Viewer[]>((s) => api.get(`/analytics/stories/${id}/viewers`, s), [id]);
  if (story.loading) return <PageLoading />;
  if (story.error) return <ErrorBanner message={story.error} />;
  if (!story.data) return <Empty label={t("analytics.storyNotFound")} />;
  const s = story.data;
  const breakdownEntries = Object.entries(s.reaction_breakdown ?? {});

  return (
    <div className="space-y-5">
      <PageHeader
        title={`Story #${s.telegram_story_id}`}
        subtitle={t("analytics.storyHistory")}
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <StatCard label={t("analytics.views")} value={s.views ?? "—"} accent />
        <StatCard label={t("analytics.knownViewers")} value={s.known_viewers} />
        <StatCard label={t("analytics.reactions")} value={s.reactions ?? "—"} accentKey="red" />
        <StatCard label={t("analytics.forwards")} value={s.forwards ?? "—"} accentKey="sky" />
        <StatCard label="ER" value={s.er == null ? "—" : `${s.er.toFixed(2)}%`} accentKey="indigo" />
      </div>

      <Card>
        <CardHeader title={t("analytics.snapshots")} />
        {points.loading ? (
          <div className="flex justify-center p-6"><Spinner /></div>
        ) : points.data?.length ? (
          <div className="max-h-72 overflow-auto">
            <table className="w-full overflow-x-auto text-left text-sm">
              <thead>
                <tr className="text-xs text-slate-400">
                  <th className="px-5 py-3">{t("analytics.time")}</th>
                  <th className="px-5 py-3">{t("analytics.views")}</th>
                  <th className="px-5 py-3">{t("analytics.reactions")}</th>
                  <th className="px-5 py-3">{t("analytics.forwards")}</th>
                </tr>
              </thead>
              <tbody>
                {points.data.map((p, i) => (
                  <tr key={i} className="border-t border-slate-100 dark:border-slate-800">
                    <td className="px-5 py-2">{new Date(p.collected_at).toLocaleString(locale)}</td>
                    <td className="px-5 py-2">{p.views ?? "—"}</td>
                    <td className="px-5 py-2">{p.reactions ?? "—"}</td>
                    <td className="px-5 py-2">{p.forwards ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty label={t("analytics.noSnapshots")} />
        )}
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title={t("analytics.reactions")} />
          {breakdownEntries.length ? (
            <div className="space-y-2 p-5">
              {breakdownEntries.map(([reaction, count]) => (
                <div key={reaction} className="flex items-center justify-between gap-3">
                  <span className="min-w-0 truncate text-sm text-slate-700 dark:text-slate-200">{reaction}</span>
                  <span className="text-sm font-semibold text-slate-900 dark:text-slate-50">{count}</span>
                </div>
              ))}
            </div>
          ) : (
            <Empty label={t("analytics.noReactions")} />
          )}
        </Card>

        <Card>
          <CardHeader title={t("analytics.viewers")} subtitle={`${s.known_viewers} ${t("analytics.viewersKnown")}`} />
          {viewers.loading ? (
            <div className="flex justify-center p-6"><Spinner /></div>
          ) : viewers.data?.length ? (
            <div className="max-h-64 overflow-auto">
              <div className="divide-y divide-slate-100 dark:divide-slate-800">
                {viewers.data.map((v) => (
                  <div key={v.telegram_user_id} className="flex items-center gap-3 px-5 py-3">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-slate-800 dark:text-slate-100">
                        {v.username
                          ? <a href={`https://t.me/${v.username}`} target="_blank" rel="noopener noreferrer" className="text-emerald-600 hover:underline dark:text-emerald-400">@{v.username}</a>
                          : [v.first_name, v.last_name].filter(Boolean).join(" ") || `User ${v.telegram_user_id}`}
                      </div>
                      {v.viewed_at && <div className="text-xs text-slate-400">{new Date(v.viewed_at).toLocaleString(locale)}</div>}
                    </div>
                    {v.reaction && <span className="shrink-0 text-lg">{v.reaction}</span>}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <Empty label={t("analytics.noViewers")} />
          )}
        </Card>
      </div>
    </div>
  );
}