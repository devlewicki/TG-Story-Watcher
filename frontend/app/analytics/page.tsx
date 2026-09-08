"use client";

import { useState } from "react";
import Link from "next/link";

import { api, type Account } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { useTranslation, useLocale } from "@/lib/i18n";
import { Button, Card, CardHeader, Empty, ErrorBanner, Icon, PageHeader, PageLoading, Segmented, Spinner, StatCard } from "@/components/ui";

type Summary = { story_id: number; telegram_story_id: number; views: number | null; reactions: number | null; forwards: number | null; known_viewers: number; er: number | null; published_at: string | null };
type Overview = { stories: number; views: number; known_viewers: number; reactions: number; forwards: number; average_views: number; average_er: number; top_stories: Summary[] };
type RecentEvent = { type: "view" | "reaction"; story_id: number; telegram_story_id: number; user_id: number; username: string | null; first_name: string | null; last_name: string | null; reaction: string | null; occurred_at: string };

export default function AnalyticsPage() {
  const { t } = useTranslation();
  const locale = useLocale();


  const accounts = useFetch<Account[]>((signal) => api.get<Account[]>(signal ? `/accounts` : "/accounts", signal), []);

  const [period, setPeriod] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("analytics_period") || "all";
    }
    return "all";
  });
  const { data: overview, loading: overviewLoading, error: overviewError, refresh: refreshOverview } = useFetch<Overview>(
    (signal) => api.get(`/analytics/overview?period=${period}`, signal),
    [period]
  );
  const recent = useFetch<RecentEvent[]>((signal) => api.get(`/analytics/recent-events?limit=30`, signal), []);



  const [syncing, setSyncing] = useState(false);
  const sync = async () => {
    setSyncing(true);
    try {
      const accs = await api.get<{ id: number }[]>("/accounts");
      for (const acc of accs) await api.post("/analytics/sync?account_id=" + acc.id);
      await refreshOverview();
    } finally {
      setSyncing(false);
    }
  };

  if (accounts.loading) return <PageLoading />;
  if (accounts.error) return <ErrorBanner message={accounts.error} />;
  const hasPremium = accounts.data?.some((a) => a.is_premium) ?? false;

  if (!hasPremium) {
    return (
      <div className="space-y-5">
        <PageHeader title={t("analytics.title")} />
        <Card className="p-6">
          <div className="flex flex-col items-center text-center">
            <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-amber-100 text-2xl dark:bg-amber-500/15">
              👑
            </div>
            <h2 className="text-lg font-semibold text-slate-800 dark:text-slate-100">
              {t("analytics.premiumRequired")}
            </h2>
            <p className="mt-2 max-w-md text-sm text-slate-500 dark:text-slate-400">
              {t("analytics.premiumDesc1")}
            </p>
            <p className="mt-2 max-w-md text-sm text-slate-500 dark:text-slate-400">
              {t("analytics.premiumDesc2", { link: "" })}{" "}
              <Link href="/stories" className="font-medium text-emerald-600 hover:underline dark:text-emerald-400">{t("analytics.storiesLink")}</Link>
            </p>
          </div>
        </Card>
      </div>
    );
  }

  if (overviewLoading) return <PageLoading />;
  if (overviewError) return <ErrorBanner message={overviewError} />;
  if (!overview) return <Empty label={t("analytics.noAnalytics")} />;

  return (
    <div className="space-y-5">
      {/* Header */}
      <PageHeader
        title={t("analytics.accountStats")}
        right={
          <div className="flex flex-wrap items-center gap-2">
            <Segmented
              value={period}
              onChange={(p) => {
                setPeriod(p);
                localStorage.setItem("analytics_period", p);
              }}
              options={[
                { value: "today" as const, label: t("analytics.today") },
                { value: "7d" as const, label: t("analytics.days7") },
                { value: "30d" as const, label: t("analytics.days30") },
                { value: "90d" as const, label: t("analytics.days90") },
                { value: "all" as const, label: t("analytics.allTime") },
              ]}
            />
            <Button onClick={sync} disabled={syncing}>
              <Icon name="refresh" className="h-4 w-4" />
              {syncing ? t("analytics.syncing") : t("analytics.sync")}
            </Button>
          </div>
        }
      />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
        <StatCard label={t("analytics.storiesLabel")} value={overview.stories} />
        <StatCard label={t("analytics.views")} value={overview.views} accent />
        <StatCard label={t("analytics.viewers")} value={overview.known_viewers} />
        <StatCard label={t("analytics.reactions")} value={overview.reactions} accentKey="red" />
        <StatCard label={t("analytics.forwards")} value={overview.forwards} accentKey="sky" />
        <StatCard label={t("analytics.avgER")} value={`${overview.average_er == null ? 0 : Number(overview.average_er).toFixed(2)}%`} accentKey="indigo" />
      </div>

      {/* Recent actions + Top stories */}
      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title={t("analytics.recentActions")} subtitle={t("analytics.recentSubtitle")} />
          {recent.loading ? (
            <div className="flex justify-center p-6"><Spinner /></div>
          ) : recent.data?.length ? (
            <div className="divide-y divide-slate-100 dark:divide-slate-800">
              {recent.data.map((event, index) => (
                <div key={`${event.story_id}-${event.user_id}-${event.occurred_at}-${index}`} className="flex items-center gap-3 px-5 py-3 text-sm">
                  <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${event.type === "reaction" ? "bg-rose-100 text-rose-500 dark:bg-rose-500/15 dark:text-rose-400" : "bg-sky-100 text-sky-500 dark:bg-sky-500/15 dark:text-sky-400"}`}>
                    <Icon name={event.type === "reaction" ? "heart" : "eye"} className="h-4 w-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate">
                      <span className="font-medium">{event.username ? <a href={`https://t.me/${event.username}`} target="_blank" rel="noopener noreferrer" className="text-emerald-600 hover:underline dark:text-emerald-400">@{event.username}</a> : [event.first_name, event.last_name].filter(Boolean).join(" ") || `User ${event.user_id}`}</span>
                      <span className="ml-2 text-slate-500"> {event.type === "reaction" ? t("analytics.reactedWith", { reaction: event.reaction || "" }) : t("analytics.viewedStory")}</span> <Link className="font-medium text-emerald-600 hover:underline" href={`/analytics/stories/${event.story_id}`}>#{event.telegram_story_id}</Link>
                    </div>
                    <div className="text-xs text-slate-400">{new Date(event.occurred_at).toLocaleString(locale)}</div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <Empty label={t("analytics.noRecentActions")} />
          )}
        </Card>

        <Card>
          <CardHeader title={t("analytics.topStories")} subtitle={
            period === "all" ? t("analytics.topStoriesAllTime") :
            period === "today" ? t("analytics.today") :
            t("analytics.topStoriesPeriod", { days: period.replace("d", "") })
          } />
          {overview.top_stories.length === 0 ? (
            <Empty label={t("analytics.noStoriesSynced")} />
          ) : (
            <div className="divide-y divide-slate-100 dark:divide-slate-800">
              {overview.top_stories.map((story, index) => (
                <Link href={`/analytics/stories/${story.story_id}`} key={story.story_id} className="flex items-center gap-4 px-5 py-4 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                  <span className="w-6 text-sm font-semibold text-slate-400">{index + 1}</span>
                  <span className="min-w-0 flex-1">
                    <span className="font-medium">Story #{story.telegram_story_id}</span>
                    <span className="ml-3 text-xs text-slate-400">{story.published_at ? new Date(story.published_at).toLocaleString(locale) : ""}</span>
                  </span>
                  <span className="text-sm text-slate-500"><Icon name="eye" className="mr-0.5 inline h-3.5 w-3.5 align-[-1px]" /> {story.views ?? "—"}</span>
                  <span className="text-sm text-slate-500"><Icon name="heart" className="mr-0.5 inline h-3.5 w-3.5 align-[-1px]" /> {story.reactions ?? "—"}</span>
                  <span className="w-20 text-right text-sm font-medium text-emerald-600">{story.er == null ? "—" : `${story.er.toFixed(2)}%`}</span>
                </Link>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
