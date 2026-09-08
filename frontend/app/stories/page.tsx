"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, type Story } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { useTranslation } from "@/lib/i18n";
import { Avatar, Button, Card, Empty, ErrorBanner, Icon, PageHeader, PageLoading } from "@/components/ui";
import { formatTime } from "@/lib/format";

const PAGE = 200;

export default function StoriesPage() {
  const { t } = useTranslation();
  const [items, setItems] = useState<Story[] | null>(null);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async (offset: number, append: boolean) => {
    if (append) setLoadingMore(true);
    else setLoading(true);
    setError("");
    try {
      const [list, cnt] = await Promise.all([
        api.get<Story[]>(`/stories?limit=${PAGE}&offset=${offset}`),
        append ? Promise.resolve(null) : api.get<{ count: number }>("/stories/count"),
      ]);
      setTotal(cnt?.count ?? 0);
      setItems((prev) => (append ? [...(prev ?? []), ...list] : list));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, []);

  useEffect(() => {
    load(0, false);
  }, [load]);

  if (loading) return <PageLoading />;
  if (error && !items) return <ErrorBanner message={error} />;

  const list = items ?? [];
  const shown = list.length;

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("stories.title")}
        subtitle={
          <>
            {shown < total
              ? t("stories.shown", { shown, total })
              : t("stories.count", { total, one: total, few: total, many: total })}
            {". "}
            <Link href="/" className="text-emerald-600 hover:underline dark:text-emerald-400">
              {t("stories.liveFeed")}
            </Link>
          </>
        }
        right={
          <Button variant="secondary" onClick={() => load(0, false)}>
            <Icon name="refresh" className="h-4 w-4" />
            {t("common.refresh")}
          </Button>
        }
      />

      {error && <ErrorBanner message={error} />}

      {list.length === 0 ? (
        <Card>
          <Empty label={t("stories.noStories")} />
        </Card>
      ) : (
        <>
          <Card>
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {list.map((s) => (
                <li
                  key={s.id}
                  className="flex items-center gap-3.5 px-5 py-3 transition-colors hover:bg-slate-50/60 dark:hover:bg-slate-800/40"
                >
                  <Avatar name={s.author_name || s.author_username || "?"} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-slate-800 dark:text-slate-100">
                      {s.author_name || "—"}
                      {s.author_username && (
                        <a href={`https://t.me/${s.author_username}`} target="_blank" rel="noopener noreferrer" className="ml-1.5 font-normal text-emerald-600 hover:underline dark:text-emerald-400">
                          @{s.author_username}
                        </a>
                      )}
                    </div>
                    <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-400">
                      {s.last_viewed_at ? (
                        <>
                          <span className="rounded bg-emerald-50 px-1.5 py-0.5 font-medium text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400">
                            {t("stories.viewed")} {formatTime(s.last_viewed_at)}
                          </span>
                          <span className="inline-flex items-center gap-1"><Icon name="eye" className="h-3.5 w-3.5" /> {s.view_count}</span>
                        </>
                      ) : (
                        <span>{t("stories.notViewed")}</span>
                      )}
                      <span className="text-slate-300 dark:text-slate-600">·</span>
                      <span>{s.source}</span>
                      <span className="text-slate-300 dark:text-slate-600">·</span>
                      <span title={`peer ${s.peer_id}`}>#{s.telegram_story_id}</span>
                    </div>
                  </div>
                  {s.liked ? (
                    <span
                      className="flex items-center gap-1 text-sm text-rose-500 dark:text-rose-400"
                      title={t("stories.autoLike")}
                    >
                      {s.like_emoji || "❤️"}
                    </span>
                  ) : (
                    <Icon name="heart" className="h-4 w-4 text-slate-300 dark:text-slate-600" />
                  )}
                  <span className="w-24 shrink-0 text-right text-xs text-slate-400">
                    {s.last_viewed_at ? "" : formatTime(s.published_at)}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
          {shown < total && (
            <div className="flex justify-center">
              <Button
                variant="secondary"
                onClick={() => load(shown, true)}
                disabled={loadingMore}
              >
                {loadingMore ? t("common.loading") : t("stories.showMore", { count: Math.min(PAGE, total - shown) })}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
