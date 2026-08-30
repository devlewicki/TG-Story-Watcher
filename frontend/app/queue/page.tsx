"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type QueueItem } from "@/lib/api";
import { Avatar, Badge, Button, Card, Empty, ErrorBanner, Spinner } from "@/components/ui";
import { formatTime } from "@/lib/format";

const ACTIVE = ["PENDING", "WAITING_DELAY", "PROCESSING"];
const PAGE = 200;

function ItemRow({ item, onCancel, onRetry }: { item: QueueItem; onCancel: (id: number) => void; onRetry: (id: number) => void }) {
  const name = item.story?.author_name || "—";
  const username = item.story?.author_username;
  return (
    <li className="flex items-center gap-3.5 px-5 py-3 transition-colors hover:bg-slate-50/60 dark:hover:bg-slate-800/40">
      <Avatar name={name} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-slate-800 dark:text-slate-100">
          {name}
          {username && (
            <span className="ml-1.5 font-normal text-slate-400">@{username}</span>
          )}
        </div>
        <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-400">
          <span>
            {item.story
              ? `${item.story.peer_id}/${item.story.telegram_story_id}`
              : `story #${item.story_id}`}
          </span>
          {item.attempts > 1 && <span>· попыток: {item.attempts}</span>}
          {item.error && (
            <span className="truncate text-red-500 dark:text-red-400" title={item.error}>
              · {item.error}
            </span>
          )}
        </div>
      </div>
      <span className="w-28 shrink-0 text-right text-xs text-slate-400">
        {formatTime(item.scheduled_at)}
      </span>
      <div className="flex w-24 shrink-0 justify-end gap-1">
        <Badge status={item.status} />
      </div>
      <div className="flex w-20 shrink-0 items-center justify-end gap-1">
        {!["VIEWED", "CANCELLED"].includes(item.status) && (
          <button
            onClick={() => onCancel(item.id)}
            title="Отменить"
            className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-500/10"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" className="h-4 w-4">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        )}
        {item.status === "FAILED" && (
          <button
            onClick={() => onRetry(item.id)}
            title="Повторить"
            className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-700 dark:hover:text-slate-200"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
              <path d="M20 11a8 8 0 1 0-2 5.3" />
              <path d="M20 4v7h-7" />
            </svg>
          </button>
        )}
      </div>
    </li>
  );
}

export default function QueuePage() {
  const [items, setItems] = useState<QueueItem[] | null>(null);
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
        api.get<QueueItem[]>(`/queue?limit=${PAGE}&offset=${offset}`),
        append ? Promise.resolve(null) : api.get<{ count: number }>("/queue/count"),
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

  const act = async (path: string) => {
    try {
      await api.post(path);
      load(0, false);
    } catch (e) {
      alert((e as Error).message);
    }
  };

  const stats = useMemo(() => {
    const list = items ?? [];
    return {
      active: list.filter((i) => ACTIVE.includes(i.status)).length,
      viewed: list.filter((i) => i.status === "VIEWED").length,
      failed: list.filter((i) => i.status === "FAILED").length,
      total: list.length,
    };
  }, [items]);

  if (loading) return <Spinner />;
  if (error && !items) return <ErrorBanner message={error} />;

  const list = items ?? [];
  const shown = list.length;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Очередь</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {shown === 0
              ? "Очередь пуста"
              : shown < total
              ? `${stats.active} в работе · ${stats.viewed} просмотрено · показано ${shown}/${total}`
              : `${stats.active} в работе · ${stats.viewed} просмотрено из ${total}${stats.failed ? ` · ${stats.failed} ошибок` : ""}`}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => load(0, false)}>↻ Обновить</Button>
          <Button
            variant="danger"
            onClick={() => {
              if (confirm("Очистить активную очередь?")) act("/queue/clear");
            }}
          >
            Очистить
          </Button>
        </div>
      </div>

      {error && <ErrorBanner message={error} />}

      {list.length === 0 ? (
        <Card>
          <Empty label="Очередь пуста" />
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
                {loadingMore ? "Загружаем…" : `Показать ещё (${Math.min(PAGE, total - shown)})`}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}