"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api, type QueueItem } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import { Avatar, Badge, Button, Card, Empty, ErrorBanner, Icon, IconButton, PageHeader, PageLoading } from "@/components/ui";
import { formatTime } from "@/lib/format";
import { friendlyError } from "@/lib/errors";

const PAGE = 200;

function ItemRow({ item, onCancel, onRetry }: { item: QueueItem; onCancel: (id: number) => void; onRetry: (id: number) => void }) {
  const { t } = useTranslation();
  const name = item.story?.author_name || "—";
  const username = item.story?.author_username;
  return (
    <li className="flex items-center gap-3.5 px-5 py-3 transition-colors hover:bg-slate-50/60 dark:hover:bg-slate-800/40">
      <Avatar name={name} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-slate-800 dark:text-slate-100">
          {name}
          {username && (
            <a href={`https://t.me/${username}`} target="_blank" rel="noopener noreferrer" className="ml-1.5 font-normal text-emerald-600 hover:underline dark:text-emerald-400">@{username}</a>
          )}
        </div>
        <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-400">
          <span>
            {item.story
              ? `${item.story.peer_id}/${item.story.telegram_story_id}`
              : `story #${item.story_id}`}
          </span>
          {item.attempts > 1 && <span>· {t("queue.attempts")}: {item.attempts}</span>}
          {item.error && (
            <span className="truncate text-red-500 dark:text-red-400" title={item.error}>
              · {item.error}
            </span>
          )}
        </div>
      </div>
      <span className="hidden shrink-0 text-right text-xs text-slate-400 sm:block">
        {formatTime(item.scheduled_at)}
      </span>
      <div className="flex w-24 shrink-0 justify-end gap-1">
        <Badge status={item.status} />
      </div>
      <div className="flex w-20 shrink-0 items-center justify-end gap-1">
        {!["VIEWED", "CANCELLED"].includes(item.status) && (
          <IconButton
            label={t("queue.cancel")}
            onClick={() => onCancel(item.id)}
            className="hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-500/10"
          >
            <Icon name="close" className="h-4 w-4" />
          </IconButton>
        )}
        {item.status === "FAILED" && (
          <IconButton label={t("queue.retry")} onClick={() => onRetry(item.id)}>
            <Icon name="refresh" className="h-4 w-4" />
          </IconButton>
        )}
      </div>
    </li>
  );
}

export default function QueuePage() {
  const { t } = useTranslation();
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState({ active: 0, viewed: 0, failed: 0, total: 0 });
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async (offset: number, append: boolean) => {
    if (append) setLoadingMore(true);
    else setLoading(true);
    setError("");
    try {
      const [list, statsData] = await Promise.all([
        api.get<QueueItem[]>(`/queue?limit=${PAGE}&offset=${offset}`),
        append
          ? Promise.resolve(null)
          : api.get<{ total: number; active: number; viewed: number; failed: number }>("/queue/stats"),
      ]);
      if (statsData) {
        setTotal(statsData.total);
        setStats({
          active: statsData.active,
          viewed: statsData.viewed,
          failed: statsData.failed,
          total: statsData.total,
        });
      }
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

  const act = async (path: string) => {
    try {
      await api.post(path);
      load(0, false);
    } catch (e) {
      setError(friendlyError(e));
    }
  };

  if (loading) return <PageLoading />;
  if (error && !items) return <ErrorBanner message={error} />;

  const list = items ?? [];
  const shown = list.length;

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("queue.title")}
        subtitle={
          shown === 0
            ? t("queue.empty")
            : shown < total
            ? `${stats.active} ${t("queue.active")} · ${stats.viewed} ${t("queue.viewed")} · ${t("queue.shown")} ${shown}/${total}`
            : `${stats.active} ${t("queue.active")} · ${stats.viewed} ${t("queue.viewed")} ${t("dashboard.of")} ${total}${stats.failed ? ` · ${stats.failed} ${t("queue.errors")}` : ""}`
        }
        right={
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => load(0, false)}>
              <Icon name="refresh" className="h-4 w-4" />
              {t("common.refresh")}
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                if (confirm(t("queue.clearConfirm"))) act("/queue/clear");
              }}
            >
              <Icon name="trash" className="h-4 w-4" />
              {t("queue.clear")}
            </Button>
          </div>
        }
      />

      {error && <ErrorBanner message={error} />}

      {list.length === 0 ? (
        <Card>
          <Empty label={t("queue.empty")} />
        </Card>
      ) : (
        <>
          <Card>
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {list.map((item) => (
                <ItemRow
                  key={item.id}
                  item={item}
                  onCancel={(id) => act(`/queue/${id}/cancel`)}
                  onRetry={(id) => act(`/queue/${id}/retry`)}
                />
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
                {loadingMore ? t("common.loading") : t("queue.showMore", { count: Math.min(PAGE, total - shown) })}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
