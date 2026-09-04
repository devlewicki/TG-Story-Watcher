"use client";

import { useState, useEffect } from "react";
import Link from "next/link";

import { api, type Account } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { useTranslation, useLocale } from "@/lib/i18n";
import { Button, Card, CardHeader, Empty, ErrorBanner, Spinner, StatCard } from "@/components/ui";

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
  const [tzOffset, setTzOffset] = useState(0);

  useEffect(() => {
    const offset = -new Date().getTimezoneOffset() / 60;
    setTzOffset(offset);
  }, []);

  const { data: overview, loading: overviewLoading, error: overviewError, refresh: refreshOverview } = useFetch<Overview>(
    (signal) => api.get(`/analytics/overview?period=${period}&tz_offset=${tzOffset}`, signal),
    [period, tzOffset]
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

  if (accounts.loading) return <Spinner />;
  if (accounts.error) return <ErrorBanner message={accounts.error} />;
  const hasPremium = accounts.data?.some((a) => a.is_premium) ?? false;

  if (!hasPremium) {
    return (
      <div className="space-y-5">
        <div>
          <h1 className="text-xl font-semibold">{t("analytics.title")}</h1>
        </div>
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

  if (overviewLoading) return <Spinner />;
  if (overviewError) return <ErrorBanner message={overviewError} />;
  if (!overview) return <Empty label={t("analytics.noAnalytics")} />;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{t("analytics.accountStats")}</h1>
        </div>
        <div className="flex gap-2">
          <div className="flex rounded-xl border border-slate-300 p-0.5 dark:border-slate-700">
            {[
              { value: "today", label: t("analytics.today") },
              { value: "7d", label: t("analytics.days7") },
              { value: "30d", label: t("analytics.days30") },
              { value: "90d", label: t("analytics.days90") },
              { value: "all", label: t("analytics.allTime") },
            ].map((p) => (
              <button
                key={p.value}
                onClick={() => {
                  setPeriod(p.value);
                  localStorage.setItem("analytics_period", p.value);
                }}
                className={`rounded-lg px-3 py-1.5 text-sm ${
                  period === p.value ? "bg-emerald-600 text-white" : "text-slate-500"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <Button onClick={sync} disabled={syncing}>
            {syncing ? t("analytics.syncing") : t("analytics.sync")}
          </Button>
        </div>
      </div>



      <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
        <StatCard label={t("analytics.storiesLabel")} value={overview.stories} />
        <StatCard label={t("analytics.views")} value={overview.views} accent />
        <StatCard label={t("analytics.viewers")} value={overview.known_viewers} />
        <StatCard label={t("analytics.reactions")} value={overview.reactions} accentKey="red" />
        <StatCard label={t("analytics.forwards")} value={overview.forwards} accentKey="sky" />
        <StatCard label={t("analytics.avgER")} value={`${overview.average_er.toFixed(2)}%`} accentKey="indigo" />
      </div>

      {/* Recent actions + Top stories */}
      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title={t("analytics.recentActions")} subtitle={t("analytics.recentSubtitle")} />
          {recent.loading ? (
            <div className="p-5"><Spinner /></div>
          ) : recent.data?.length ? (
            <div className="divide-y divide-slate-100 dark:divide-slate-800">
              {recent.data.map((event, index) => (
                <div key={`${event.story_id}-${event.user_id}-${event.occurred_at}-${index}`} className="flex items-center gap-3 px-5 py-3 text-sm">
                  <span className={`flex h-8 w-8 items-center justify-center rounded-full ${event.type === "reaction" ? "bg-rose-100 dark:bg-rose-500/15" : "bg-sky-100 dark:bg-sky-500/15"}`}>
                    {event.type === "reaction" ? "❤️" : "👁"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate">
                      <span className="font-medium">{event.username ? `@${event.username}` : [event.first_name, event.last_name].filter(Boolean).join(" ") || `User ${event.user_id}`}</span>
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
                  <span className="flex-1">
                    <span className="font-medium">Story #{story.telegram_story_id}</span>
                    <span className="ml-3 text-xs text-slate-400">{story.published_at ? new Date(story.published_at).toLocaleString(locale) : ""}</span>
                  </span>
                  <span className="text-sm text-slate-500">👁 {story.views ?? "—"}</span>
                  <span className="text-sm text-slate-500">❤️ {story.reactions ?? "—"}</span>
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
