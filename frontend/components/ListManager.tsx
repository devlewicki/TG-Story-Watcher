"use client";

import { useState } from "react";
import { api, type ListEntry } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Button, Card, CardHeader, Empty, ErrorBanner, Spinner } from "@/components/ui";
import { timeAgo } from "@/lib/format";

export function ListManager({ title, kind }: { title: string; kind: "whitelist" | "blacklist" }) {
  const { data, loading, error, refresh } = useFetch<ListEntry[]>((s) =>
    api.get<ListEntry[]>(`/${kind}`, s)
  );
  const [accountId, setAccountId] = useState("1");
  const [username, setUsername] = useState("");
  const [peerId, setPeerId] = useState("");
  const [comment, setComment] = useState("");

  const add = async () => {
    try {
      await api.post(`/${kind}`, {
        account_id: Number(accountId) || 1,
        username: username.trim() || null,
        peer_id: peerId.trim() ? Number(peerId) : null,
        comment: comment.trim() || null,
      });
      setUsername("");
      setPeerId("");
      setComment("");
      refresh();
    } catch (e) {
      alert((e as Error).message);
    }
  };

  const remove = async (id: number) => {
    try {
      await api.delete(`/${kind}/${id}`);
      refresh();
    } catch (e) {
      alert((e as Error).message);
    }
  };

  if (loading) return <Spinner />;
  if (error) return <ErrorBanner message={error} />;
  const items = data ?? [];

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">{title}</h1>

      <Card className="p-4">
        <CardHeader title="Добавить запись" />
        <div className="mt-3 grid gap-3 md:grid-cols-5">
          <div>
            <label className="text-xs text-slate-500">ID аккаунта</label>
            <input value={accountId} onChange={(e) => setAccountId(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800" />
          </div>
          <div>
            <label className="text-xs text-slate-500">Username</label>
            <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="@user" className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800" />
          </div>
          <div>
            <label className="text-xs text-slate-500">Telegram ID</label>
            <input value={peerId} onChange={(e) => setPeerId(e.target.value)} placeholder="необязательно" className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800" />
          </div>
          <div>
            <label className="text-xs text-slate-500">Комментарий</label>
            <input value={comment} onChange={(e) => setComment(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800" />
          </div>
          <div className="flex items-end">
            <Button className="w-full" onClick={add}>Добавить</Button>
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader title={`${items.length} записей`} right={<Button variant="secondary" onClick={refresh}>↻</Button>} />
        {items.length === 0 ? (
          <Empty label={`${title} пуст`} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
                  <th className="px-4 py-2">Username</th>
                  <th className="px-4 py-2">Peer ID</th>
                  <th className="px-4 py-2">Комментарий</th>
                  <th className="px-4 py-2">Добавлен</th>
                  <th className="px-4 py-2 text-right">Действия</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {items.map((e) => (
                  <tr key={e.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                    <td className="px-4 py-2 font-medium">{e.username ? `@${e.username}` : "—"}</td>
                    <td className="px-4 py-2 text-slate-500">{e.peer_id ?? "—"}</td>
                    <td className="px-4 py-2 text-slate-500">{e.comment || "—"}</td>
                    <td className="px-4 py-2 text-slate-500">{timeAgo(e.created_at)}</td>
                    <td className="px-4 py-2 text-right">
                      <Button variant="danger" onClick={() => remove(e.id)}>Удалить</Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}