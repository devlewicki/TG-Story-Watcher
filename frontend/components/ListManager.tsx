"use client";

import { useState } from "react";
import { api, type Account, type ListEntry } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { useTranslation } from "@/lib/i18n";
import { Button, Card, CardHeader, Empty, ErrorBanner, Icon, IconButton, PageHeader, PageLoading } from "@/components/ui";
import { timeAgo } from "@/lib/format";

export function ListManager({ title, kind }: { title: string; kind: "whitelist" | "blacklist" }) {
  const { t } = useTranslation();
  const { data, loading, error, refresh } = useFetch<ListEntry[]>((s) =>
    api.get<ListEntry[]>(`/${kind}`, s)
  );
  const { data: accounts } = useFetch<Account[]>((s) => api.get<Account[]>("/accounts", s), []);
  const [accountId, setAccountId] = useState<string>("");
  const [username, setUsername] = useState("");
  const [peerId, setPeerId] = useState("");
  const [comment, setComment] = useState("");

  const add = async () => {
    try {
      const validAccounts = accounts ?? [];
      const chosen = validAccounts.find((a) => String(a.id) === accountId) ?? validAccounts[0];
      const account_id = chosen?.id ?? null;
      if (account_id === null) {
        alert(t("listManager.noAccount"));
        return;
      }
      const normalizedUsername = username.trim().replace(/^@+/, "");
      await api.post(`/${kind}`, {
        account_id,
        username: normalizedUsername || null,
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

  if (loading) return <PageLoading />;
  if (error) return <ErrorBanner message={error} />;
  const items = data ?? [];

  return (
    <div className="space-y-4">
      <PageHeader title={title} />

      <Card className="p-4">
        <CardHeader title={t("listManager.addRecord")} />
        <div className="mt-3 grid gap-3 md:grid-cols-5">
          <div>
            <label className="text-xs text-slate-500">{t("listManager.accountId")}</label>
            <select
              value={accountId || (accounts?.[0] ? String(accounts[0].id) : "")}
              onChange={(e) => setAccountId(e.target.value)}
              className="mt-1 w-full sw-input"
            >
              {(accounts ?? []).length === 0 && <option value="">—</option>}
              {(accounts ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.username ? `@${a.username}` : a.phone || String(a.id)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-slate-500">{t("listManager.username")}</label>
            <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="@user" className="mt-1 w-full sw-input" />
          </div>
          <div>
            <label className="text-xs text-slate-500">{t("listManager.telegramId")}</label>
            <input value={peerId} onChange={(e) => setPeerId(e.target.value)} placeholder={t("listManager.telegramIdOptional")} className="mt-1 w-full sw-input" />
          </div>
          <div>
            <label className="text-xs text-slate-500">{t("listManager.comment")}</label>
            <input value={comment} onChange={(e) => setComment(e.target.value)} className="mt-1 w-full sw-input" />
          </div>
          <div className="flex items-end">
            <Button className="w-full" onClick={add}>{t("listManager.add")}</Button>
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader title={`${items.length} ${t("listManager.records")}`} right={<IconButton label={t("common.refresh")} onClick={refresh}><Icon name="refresh" className="h-4 w-4" /></IconButton>} />
        {items.length === 0 ? (
          <Empty label={t("listManager.empty", { title })} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
                  <th className="px-4 py-2">{t("listManager.colUsername")}</th>
                  <th className="px-4 py-2">{t("listManager.colPeerId")}</th>
                  <th className="px-4 py-2">{t("listManager.colComment")}</th>
                  <th className="px-4 py-2">{t("listManager.colAdded")}</th>
                  <th className="px-4 py-2 text-right">{t("listManager.colActions")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {items.map((e) => (
                  <tr key={e.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                    <td className="px-4 py-2 font-medium">{e.username ? <a href={`https://t.me/${e.username}`} target="_blank" rel="noopener noreferrer" className="text-emerald-600 hover:underline dark:text-emerald-400">@{e.username}</a> : "—"}</td>
                    <td className="px-4 py-2 text-slate-500">{e.peer_id ?? "—"}</td>
                    <td className="px-4 py-2 text-slate-500">{e.comment || "—"}</td>
                    <td className="px-4 py-2 text-slate-500">{timeAgo(e.created_at)}</td>
                    <td className="px-4 py-2 text-right">
                      <IconButton
                        label={t("common.delete")}
                        onClick={() => remove(e.id)}
                        className="hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-500/10"
                      >
                        <Icon name="trash" className="h-4 w-4" />
                      </IconButton>
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
