"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type ActivityEvent, type View } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import { Button, Badge, Card, CardHeader, Empty, ErrorBanner, Spinner } from "@/components/ui";
import { formatTime, timeAgo } from "@/lib/format";

const PAGE = 300;

export default function HistoryPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<"views" | "activity">("views");
  const [views, setViews] = useState<View[] | null>(null);
  const [viewsTotal, setViewsTotal] = useState(0);
  const [viewsLoading, setViewsLoading] = useState(true);
  const [act, setAct] = useState<ActivityEvent[] | null>(null);
  const [actTotal, setActTotal] = useState(0);
  const [actLoading, setActLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");

  const loadViews = useCallback(async (offset: number, append: boolean) => {
    setError("");
    try {
      const [list, cnt] = await Promise.all([
        api.get<View[]>(`/history/views?limit=${PAGE}&offset=${offset}`),
        append ? Promise.resolve(null) : api.get<{ count: number }>("/history/views/count"),
      ]);
      setViewsTotal(cnt?.count ?? 0);
      setViews((prev) => (append ? [...(prev ?? []), ...list] : list));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setViewsLoading(false);
      setLoadingMore(false);
    }
  }, []);

  const loadAct = useCallback(async (offset: number, append: boolean) => {
    setError("");
    try {
      const [list, cnt] = await Promise.all([
        api.get<ActivityEvent[]>(`/history/activity?limit=${PAGE}&offset=${offset}`),
        append ? Promise.resolve(null) : api.get<{ count: number }>("/history/activity/count"),
      ]);
      setActTotal(cnt?.count ?? 0);
      setAct((prev) => (append ? [...(prev ?? []), ...list] : list));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setActLoading(false);
      setLoadingMore(false);
    }
  }, []);

  useEffect(() => {
    loadViews(0, false);
  }, [loadViews]);
  useEffect(() => {
    loadAct(0, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const list = tab === "views" ? views : act;
  const total = tab === "views" ? viewsTotal : actTotal;
  const shown = list?.length ?? 0;

  const loadMore = () => {
    setLoadingMore(true);
    if (tab === "views") loadViews(shown, true);
    else loadAct(shown, true);
  };

  if (viewsLoading || actLoading) return <Spinner />;
  if (error && !list) return <ErrorBanner message={error} />;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">{t("history.title")}</h1>
        <Button
          variant="secondary"
          onClick={() => {
            if (tab === "views") loadViews(0, false);
            else loadAct(0, false);
          }}
        >
          {t("common.refresh")}
        </Button>
      </div>

      <div className="flex gap-1">
        {(["views", "activity"] as const).map((tabKey) => (
          <button
            key={tabKey}
            onClick={() => setTab(tabKey)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
              tab === tabKey
                ? "bg-emerald-600 text-white"
                : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            }`}
          >
            {tabKey === "views" ? t("history.storyViews") : t("history.activityLog")}
          </button>
        ))}
      </div>

      {error && <ErrorBanner message={error} />}

      {tab === "views" ? (
        <Card>
          <CardHeader
            title={`${shown < viewsTotal ? t("history.shown", { shown, total: viewsTotal }) : t("history.viewsCount", { total: viewsTotal })}`}
          />
          {(views ?? []).length === 0 ? (
            <Empty label={t("history.noViews")} />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
                    <th className="px-4 py-2">{t("history.colStatus")}</th>
                    <th className="px-4 py-2">{t("history.colPeer")}</th>
                    <th className="px-4 py-2">{t("history.colStoryId")}</th>
                    <th className="px-4 py-2">{t("history.colSource")}</th>
                    <th className="px-4 py-2">{t("history.colViewed")}</th>
                    <th className="px-4 py-2">{t("history.colError")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {(views ?? []).map((v: View) => (
                    <tr key={v.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                      <td className="px-4 py-2"><Badge status={v.status} /></td>
                      <td className="px-4 py-2 text-slate-500">{v.peer_id}</td>
                      <td className="px-4 py-2 text-slate-500">{v.telegram_story_id}</td>
                      <td className="px-4 py-2 text-slate-500">{v.source || "—"}</td>
                      <td className="px-4 py-2 text-slate-500">{formatTime(v.viewed_at)}</td>
                      <td className="max-w-[200px] truncate px-4 py-2 text-red-600">{v.error || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      ) : (
        <Card>
          <CardHeader
            title={`${shown < actTotal ? t("history.shown", { shown, total: actTotal }) : t("history.eventsCount", { total: actTotal })}`}
          />
          {(act ?? []).length === 0 ? (
            <Empty label={t("history.noActivity")} />
          ) : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {(act ?? []).map((e: ActivityEvent) => (
                <li key={e.id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                  <Badge status={e.level === "ERROR" ? "ERROR" : e.event_type === "story_viewed" ? "VIEWED" : e.event_type === "story_queued" ? "PENDING" : e.level} />
                  <span className="flex-1 truncate text-slate-700 dark:text-slate-200">{e.message}</span>
                  <span className="text-xs text-slate-400">{timeAgo(e.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {shown < total && (
        <div className="flex justify-center">
          <Button variant="secondary" onClick={loadMore} disabled={loadingMore}>
            {loadingMore ? t("common.loading") : t("history.showMore", { count: Math.min(PAGE, total - shown) })}
          </Button>
        </div>
      )}
    </div>
  );
}
