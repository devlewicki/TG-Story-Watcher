"use client";

import { useCallback, useEffect, useState } from "react";
import { adminApi, type AdminQueueRow, type Paged, type QueueHealth } from "@/lib/adminApi";
import { useTranslation } from "@/lib/i18n";
import { formatTime } from "@/lib/format";
import {
  AdminCard,
  AdminCardHeader,
  AdminPagination,
  AdminSearchInput,
  AdminSelect,
  AdminStatusBadge,
  AdminTable,
  ConfirmDialog,
  EmptyRow,
  ErrorBanner,
  StatCard,
  Td,
  Th,
} from "@/components/admin/adminUi";

const STATUSES = ["PENDING", "WAITING_DELAY", "PROCESSING", "VIEWED", "SKIPPED", "FAILED", "EXPIRED", "CANCELLED"];

export default function AdminQueuePage() {
  const { t } = useTranslation();
  const [data, setData] = useState<Paged<AdminQueueRow> | null>(null);
  const [health, setHealth] = useState<QueueHealth | null>(null);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("all");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      const params = new URLSearchParams({ page: String(page), page_size: "25" });
      if (status !== "all") params.set("status", status);
      if (search) params.set("search", search);
      const [list, h] = await Promise.all([
        adminApi.get<Paged<AdminQueueRow>>(`/admin/queue?${params}`),
        adminApi.get<QueueHealth>("/admin/queue/health"),
      ]);
      setData(list);
      setHealth(h);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [page, status, search]);

  useEffect(() => {
    const iv = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(iv);
  }, [load, search]);

  async function action(path: string) {
    try {
      await adminApi.post(path);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="space-y-4">
      {error && <ErrorBanner message={error} />}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label={t("admin.nav.queue")} value={health?.active ?? "—"} tone="sky" />
        <StatCard label={t("admin.queuePage.stuck")} value={health?.stuck ?? "—"} tone="amber" />
        <StatCard label={t("admin.queuePage.failed")} value={health?.failed ?? "—"} tone="red" />
        <StatCard
          label={t("admin.queuePage.avgTime")}
          value={health?.avg_processing_seconds != null ? `${health.avg_processing_seconds}s` : "—"}
        />
      </div>

      <AdminCard>
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 p-4 dark:border-slate-800">
          <AdminSearchInput value={search} onChange={(v) => { setSearch(v); setPage(1); }} placeholder={t("admin.common.search")} />
          <AdminSelect
            value={status}
            onChange={(v) => { setStatus(v); setPage(1); }}
            options={[{ value: "all", label: t("admin.common.all") }, ...STATUSES.map((s) => ({ value: s, label: s.replace(/_/g, " ") }))]}
          />
          <div className="ml-auto flex flex-wrap gap-2">
            <button onClick={() => setConfirm("resetStuck")} className="rounded-xl border border-slate-300 px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800">
              {t("admin.queuePage.resetStuck")}
            </button>
            <button onClick={() => setConfirm("clearFinished")} className="rounded-xl border border-slate-300 px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800">
              {t("admin.queuePage.clearFinished")}
            </button>
            <button onClick={() => setConfirm("clearFailed")} className="rounded-xl border border-slate-300 px-3 py-2 text-xs font-medium text-amber-600 hover:bg-amber-50 dark:border-slate-700 dark:hover:bg-amber-500/10">
              {t("admin.queuePage.clearFailed")}
            </button>
            <button onClick={() => setConfirm("clearAll")} className="rounded-xl border border-red-200 px-3 py-2 text-xs font-medium text-red-600 hover:bg-red-50 dark:border-red-500/30 dark:hover:bg-red-500/10">
              {t("admin.queuePage.clearAll")}
            </button>
          </div>
        </div>

        <AdminTable
          head={
            <>
              <Th>{t("admin.errors.message")}</Th>
              <Th>{t("admin.accounts.account")}</Th>
              <Th>{t("admin.common.status")}</Th>
              <Th>{t("admin.queuePage.attempts")}</Th>
              <Th>{t("admin.common.created")}</Th>
              <Th className="text-right">{t("admin.common.actions")}</Th>
            </>
          }
        >
          {!data && <EmptyRow colSpan={6} label={t("common.loading")} />}
          {data && data.items.length === 0 && <EmptyRow colSpan={6} label={t("admin.common.none")} />}
          {data?.items.map((q) => (
            <tr key={q.id} className="transition-colors hover:bg-slate-50/60 dark:hover:bg-slate-800/40">
              <Td>
                <span className="block text-sm font-medium text-slate-800 dark:text-slate-100">
                  {q.story?.author_name || q.story?.author_username || `#${q.story?.id ?? "—"}`}
                </span>
                {q.error ? <span className="block max-w-xs truncate text-xs text-red-500" title={q.error}>{q.error}</span> : null}
              </Td>
              <Td className="text-xs text-slate-500 dark:text-slate-400">
                {q.account?.username ? `@${q.account.username}` : q.account?.id || "—"}
              </Td>
              <Td><AdminStatusBadge status={q.status} /></Td>
              <Td>{q.attempts}</Td>
              <Td className="text-xs text-slate-400">{formatTime(q.created_at)}</Td>
              <Td>
                <div className="flex justify-end gap-1">
                  {!["VIEWED", "CANCELLED"].includes(q.status) && (
                    <button onClick={() => action(`/admin/queue/${q.id}/cancel`)} className="rounded-lg px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">
                      {t("admin.common.cancel")}
                    </button>
                  )}
                  {["FAILED", "EXPIRED", "PROCESSING"].includes(q.status) && (
                    <button onClick={() => action(`/admin/queue/${q.id}/retry`)} className="rounded-lg px-2 py-1 text-xs text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-500/10">
                      {t("admin.common.retry")}
                    </button>
                  )}
                </div>
              </Td>
            </tr>
          ))}
        </AdminTable>
        {data && <AdminPagination page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />}
      </AdminCard>

      <ConfirmDialog
        open={confirm === "resetStuck"}
        title={t("admin.queuePage.resetStuck")}
        onConfirm={() => action("/admin/queue/reset-stuck?minutes=30")}
        onClose={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm === "clearFinished"}
        title={t("admin.queuePage.clearFinished")}
        danger
        onConfirm={() => action("/admin/queue/clear?scope=finished")}
        onClose={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm === "clearFailed"}
        title={t("admin.queuePage.clearFailed")}
        danger
        onConfirm={() => action("/admin/queue/clear?scope=failed")}
        onClose={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm === "clearAll"}
        title={t("admin.queuePage.clearAll")}
        message={t("admin.users.deleteWarning")}
        danger
        onConfirm={() => action("/admin/queue/clear?scope=all")}
        onClose={() => setConfirm(null)}
      />
    </div>
  );
}
