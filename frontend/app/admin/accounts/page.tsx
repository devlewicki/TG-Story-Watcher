"use client";

import { useCallback, useEffect, useState } from "react";
import { adminApi, type AdminAccountRow, type Paged } from "@/lib/adminApi";
import { useTranslation } from "@/lib/i18n";
import { formatTime } from "@/lib/format";
import {
  AdminCard,
  AdminPagination,
  AdminSearchInput,
  AdminSelect,
  AdminStatusBadge,
  AdminTable,
  ConfirmDialog,
  EmptyRow,
  ErrorBanner,
  Td,
  Th,
} from "@/components/admin/adminUi";

const STATUSES = [
  "ACTIVE",
  "PAUSED",
  "FLOOD_WAIT",
  "ERROR",
  "DISCONNECTED",
  "AUTH_REQUIRED",
  "BANNED_OR_RESTRICTED",
];

export default function AdminAccountsPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<Paged<AdminAccountRow> | null>(null);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState<{ kind: string; acc: AdminAccountRow } | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      const params = new URLSearchParams({ page: String(page), page_size: "20" });
      if (search) params.set("search", search);
      if (status !== "all") params.set("status", status);
      setData(await adminApi.get<Paged<AdminAccountRow>>(`/admin/accounts?${params}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [page, search, status]);

  useEffect(() => {
    const iv = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(iv);
  }, [load, search]);

  async function runAction(kind: string, id: number) {
    try {
      if (kind === "start") await adminApi.post(`/admin/accounts/${id}/start`);
      else if (kind === "pause") await adminApi.post(`/admin/accounts/${id}/pause`);
      else if (kind === "reconnect") await adminApi.post(`/admin/accounts/${id}/reconnect`);
      else if (kind === "remove") await adminApi.delete(`/admin/accounts/${id}`);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="space-y-4">
      {error && <ErrorBanner message={error} />}
      <AdminCard>
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 p-4 dark:border-slate-800">
          <AdminSearchInput value={search} onChange={(v) => { setSearch(v); setPage(1); }} placeholder={t("admin.common.search")} />
          <AdminSelect
            value={status}
            onChange={(v) => { setStatus(v); setPage(1); }}
            options={[{ value: "all", label: t("admin.common.all") }, ...STATUSES.map((s) => ({ value: s, label: s.replace(/_/g, " ") }))]}
          />
        </div>

        <AdminTable
          head={
            <>
              <Th>{t("admin.accounts.account")}</Th>
              <Th>{t("admin.common.owner")}</Th>
              <Th>{t("admin.common.status")}</Th>
              <Th>{t("admin.accounts.monitoring")}</Th>
              <Th>{t("admin.accounts.viewsToday")}</Th>
              <Th>{t("admin.accounts.lastSeen")}</Th>
              <Th className="text-right">{t("admin.common.actions")}</Th>
            </>
          }
        >
          {!data && <EmptyRow colSpan={7} label={t("common.loading")} />}
          {data && data.items.length === 0 && <EmptyRow colSpan={7} label={t("admin.common.none")} />}
          {data?.items.map((a) => (
            <tr key={a.id} className="transition-colors hover:bg-slate-50/60 dark:hover:bg-slate-800/40">
              <Td>
                <span className="block text-sm font-medium text-slate-800 dark:text-slate-100">
                  {a.username ? `@${a.username}` : a.phone_masked}
                </span>
                <span className="block text-xs text-slate-400">{a.first_name || ""} {a.last_name || ""}</span>
              </Td>
              <Td className="text-xs text-slate-500 dark:text-slate-400">{a.owner?.email || t("admin.common.none")}</Td>
              <Td><AdminStatusBadge status={a.status} /></Td>
              <Td>
                <span className={`text-xs font-medium ${a.monitoring ? "text-emerald-600 dark:text-emerald-400" : "text-slate-400"}`}>
                  {a.monitoring ? "ON" : "OFF"}
                </span>
              </Td>
              <Td>{a.views_today}</Td>
              <Td className="text-xs text-slate-400">{formatTime(a.last_seen_at)}</Td>
              <Td>
                <div className="flex justify-end gap-1">
                  {a.status !== "ACTIVE" && (
                    <button onClick={() => runAction("start", a.id)} className="rounded-lg px-2 py-1 text-xs text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-500/10">
                      {t("admin.accounts.start")}
                    </button>
                  )}
                  {a.status === "ACTIVE" && (
                    <button onClick={() => setConfirm({ kind: "pause", acc: a })} className="rounded-lg px-2 py-1 text-xs text-amber-600 hover:bg-amber-50 dark:hover:bg-amber-500/10">
                      {t("admin.accounts.pause")}
                    </button>
                  )}
                  <button onClick={() => setConfirm({ kind: "reconnect", acc: a })} className="rounded-lg px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">
                    {t("admin.accounts.reconnect")}
                  </button>
                  <button onClick={() => setConfirm({ kind: "remove", acc: a })} className="rounded-lg px-2 py-1 text-xs text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10">
                    {t("admin.common.delete")}
                  </button>
                </div>
              </Td>
            </tr>
          ))}
        </AdminTable>
        {data && <AdminPagination page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />}
      </AdminCard>

      <ConfirmDialog
        open={confirm?.kind === "pause"}
        title={t("admin.accounts.pause")}
        onConfirm={() => confirm && runAction("pause", confirm.acc.id)}
        onClose={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm?.kind === "reconnect"}
        title={t("admin.accounts.reconnect")}
        onConfirm={() => confirm && runAction("reconnect", confirm.acc.id)}
        onClose={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm?.kind === "remove"}
        title={t("admin.accounts.remove")}
        message={t("admin.accounts.removeWarning")}
        requireText="DELETE"
        danger
        confirmLabel={t("admin.common.delete")}
        onConfirm={() => confirm && runAction("remove", confirm.acc.id)}
        onClose={() => setConfirm(null)}
      />
    </div>
  );
}
