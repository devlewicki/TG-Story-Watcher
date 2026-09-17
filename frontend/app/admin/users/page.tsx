"use client";

import { useCallback, useEffect, useState } from "react";
import { adminApi, type AdminUserRow, type Paged } from "@/lib/adminApi";
import { useTranslation } from "@/lib/i18n";
import { formatTime } from "@/lib/format";
import {
  AdminCard,
  AdminPagination,
  AdminSearchInput,
  AdminSelect,
  AdminTable,
  AdminStatusBadge,
  ConfirmDialog,
  EmptyRow,
  ErrorBanner,
  Td,
  Th,
} from "@/components/admin/adminUi";
import { Avatar } from "@/components/ui";

type UserDetails = AdminUserRow & {
  accounts: { id: number; phone: string; username: string | null; status: string; monitoring: boolean }[];
  stories: number;
  rules: number;
  queue_by_status: Record<string, number>;
  activity: { id: number; event_type: string; level: string; message: string; created_at: string | null }[];
};

export default function AdminUsersPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<Paged<AdminUserRow> | null>(null);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState("");
  const [details, setDetails] = useState<UserDetails | null>(null);
  const [confirmAction, setConfirmAction] = useState<{ kind: string; user: AdminUserRow } | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      const params = new URLSearchParams({ page: String(page), page_size: "20" });
      if (search) params.set("search", search);
      if (filter !== "all") params.set("filter", filter);
      setData(await adminApi.get<Paged<AdminUserRow>>(`/admin/users?${params}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [page, search, filter]);

  useEffect(() => {
    const iv = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(iv);
  }, [load, search]);

  const openDetails = async (id: number) => {
    try {
      setDetails(await adminApi.get<UserDetails>(`/admin/users/${id}`));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  async function runAction(kind: string, userId: number) {
    try {
      if (kind === "block") await adminApi.post(`/admin/users/${userId}/block`, { blocked: true });
      else if (kind === "unblock") await adminApi.post(`/admin/users/${userId}/block`, { blocked: false });
      else if (kind === "logout") await adminApi.post(`/admin/users/${userId}/logout-all`);
      else if (kind === "clearQueue") await adminApi.post(`/admin/users/${userId}/clear-queue`);
      else if (kind === "delete") await adminApi.delete(`/admin/users/${userId}`);
      load();
      if (details?.id === userId && kind === "delete") setDetails(null);
      else if (details?.id === userId) openDetails(userId);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const confirmProps = (kind: string) => {
    const user = confirmAction?.user;
    return {
      open: confirmAction?.kind === kind && !!user,
      title:
        kind === "delete"
          ? t("admin.users.deleteUser")
          : kind === "unblock"
            ? t("admin.users.unblock")
            : kind === "block"
              ? t("admin.users.block")
              : kind === "logout"
                ? t("admin.users.logoutAll")
                : t("admin.users.clearQueue"),
      message: kind === "delete" ? t("admin.users.deleteWarning") : undefined,
      requireText: kind === "delete" ? "DELETE" : undefined,
      confirmLabel:
        kind === "delete"
          ? t("admin.common.delete")
          : kind === "unblock"
            ? t("admin.users.unblock")
            : kind === "block"
              ? t("admin.users.block")
              : kind === "logout"
                ? t("admin.users.logoutAll")
                : t("admin.users.clearQueue"),
      danger: kind === "delete",
      onConfirm: () => user && runAction(kind, user.id),
      onClose: () => setConfirmAction(null),
    };
  };

  return (
    <div className="space-y-4">
      {error && <ErrorBanner message={error} />}

      <AdminCard>
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 p-4 dark:border-slate-800">
          <AdminSearchInput value={search} onChange={(v) => { setSearch(v); setPage(1); }} placeholder={t("admin.common.search")} />
          <AdminSelect
            value={filter}
            onChange={(v) => { setFilter(v); setPage(1); }}
            options={[
              { value: "all", label: t("admin.common.all") },
              { value: "blocked", label: t("admin.users.blocked") },
              { value: "no_accounts", label: t("admin.users.noAccounts") },
            ]}
          />
        </div>

        <AdminTable
          head={
            <>
              <Th>{t("admin.users.user")}</Th>
              <Th>{t("admin.users.accounts")}</Th>
              <Th>{t("admin.users.viewsToday")}</Th>
              <Th>{t("admin.users.queue")}</Th>
              <Th>{t("admin.common.lastActivity")}</Th>
              <Th>{t("admin.common.status")}</Th>
              <Th className="text-right">{t("admin.common.actions")}</Th>
            </>
          }
        >
          {!data && <EmptyRow colSpan={7} label={t("common.loading")} />}
          {data && data.items.length === 0 && <EmptyRow colSpan={7} label={t("admin.common.none")} />}
          {data?.items.map((u) => (
            <tr key={u.id} className="transition-colors hover:bg-slate-50/60 dark:hover:bg-slate-800/40">
              <Td>
                <button onClick={() => openDetails(u.id)} className="flex items-center gap-3 text-left">
                  <Avatar name={u.email} className="h-8 w-8 text-xs" />
                  <span>
                    <span className="block text-sm font-medium text-slate-800 hover:underline dark:text-slate-100">
                      {u.first_name} {u.last_name}
                    </span>
                    <span className="block text-xs text-slate-400">{u.email}</span>
                  </span>
                </button>
              </Td>
              <Td>{u.accounts}</Td>
              <Td>{u.views_today}</Td>
              <Td>{u.queue_active}</Td>
              <Td className="text-xs text-slate-400">{formatTime(u.last_activity)}</Td>
              <Td>
                <AdminStatusBadge status={u.account_status ?? (u.blocked ? "FAILED" : "ACTIVE")} />
              </Td>
              <Td>
                <div className="flex flex-wrap justify-end gap-1">
                  <button onClick={() => setConfirmAction({ kind: u.blocked ? "unblock" : "block", user: u })} className="rounded-lg px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">
                    {u.blocked ? t("admin.users.unblock") : t("admin.users.block")}
                  </button>
                  <button onClick={() => setConfirmAction({ kind: "logout", user: u })} className="rounded-lg px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">
                    {t("admin.users.logoutAll")}
                  </button>
                  <button onClick={() => setConfirmAction({ kind: "clearQueue", user: u })} className="rounded-lg px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">
                    {t("admin.users.clearQueue")}
                  </button>
                  <button onClick={() => setConfirmAction({ kind: "delete", user: u })} className="rounded-lg px-2 py-1 text-xs text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10">
                    {t("admin.common.delete")}
                  </button>
                </div>
              </Td>
            </tr>
          ))}
        </AdminTable>
        {data && <AdminPagination page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />}
      </AdminCard>

      {/* Details drawer */}
      {details && (
        <div className="fixed inset-0 z-40">
          <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm" onClick={() => setDetails(null)} />
          <div className="absolute inset-y-0 right-0 w-full max-w-xl overflow-y-auto border-l border-slate-200 bg-white p-4 shadow-xl dark:border-slate-800 dark:bg-slate-900 sm:p-6">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-base font-semibold text-slate-900 dark:text-white">{t("admin.users.details")}</h3>
              <button onClick={() => setDetails(null)} className="rounded-lg px-2 py-1 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800">✕</button>
            </div>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div><dt className="text-xs text-slate-400">{t("admin.users.email")}</dt><dd className="text-slate-800 dark:text-slate-100">{details.email}</dd></div>
              <div><dt className="text-xs text-slate-400">{t("admin.common.created")}</dt><dd className="text-slate-800 dark:text-slate-100">{formatTime(details.created_at)}</dd></div>
              <div><dt className="text-xs text-slate-400">{t("admin.users.stories")}</dt><dd>{details.stories}</dd></div>
              <div><dt className="text-xs text-slate-400">{t("admin.users.rules")}</dt><dd>{details.rules}</dd></div>
            </dl>
            <h4 className="mt-6 text-xs font-semibold uppercase tracking-wide text-slate-400">{t("admin.nav.accounts")}</h4>
            <ul className="mt-2 space-y-2">
              {details.accounts.map((a) => (
                <li key={a.id} className="flex items-center justify-between rounded-xl border border-slate-100 px-3 py-2 text-sm dark:border-slate-800">
                  <span className="text-slate-700 dark:text-slate-200">{a.username ? `@${a.username}` : a.phone}</span>
                  <AdminStatusBadge status={a.status} />
                </li>
              ))}
              {details.accounts.length === 0 && <li className="text-sm text-slate-400">{t("admin.common.none")}</li>}
            </ul>
            <h4 className="mt-6 text-xs font-semibold uppercase tracking-wide text-slate-400">{t("admin.users.activity")}</h4>
            <ul className="mt-2 space-y-1.5">
              {details.activity.map((a) => (
                <li key={a.id} className="text-xs text-slate-500 dark:text-slate-400">
                  <span className="text-slate-700 dark:text-slate-200">{a.event_type}</span> · {a.message} · {formatTime(a.created_at)}
                </li>
              ))}
              {details.activity.length === 0 && <li className="text-sm text-slate-400">{t("admin.common.none")}</li>}
            </ul>
          </div>
        </div>
      )}

      <ConfirmDialog {...confirmProps("block")} />
      <ConfirmDialog {...confirmProps("unblock")} />
      <ConfirmDialog {...confirmProps("logout")} />
      <ConfirmDialog {...confirmProps("clearQueue")} />
      <ConfirmDialog {...confirmProps("delete")} />
    </div>
  );
}
