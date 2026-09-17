"use client";

import { useCallback, useEffect, useState } from "react";
import { adminApi, type ActivityRow, type Paged } from "@/lib/adminApi";
import { useTranslation } from "@/lib/i18n";
import { formatTime } from "@/lib/format";
import {
  AdminCard,
  AdminPagination,
  AdminSearchInput,
  AdminSelect,
  AdminStatusBadge,
  AdminTable,
  EmptyRow,
  ErrorBanner,
  Td,
  Th,
} from "@/components/admin/adminUi";

export default function AdminActivityPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<Paged<ActivityRow> | null>(null);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [level, setLevel] = useState("all");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const params = new URLSearchParams({ page: String(page), page_size: "40" });
      if (search) params.set("search", search);
      if (level !== "all") params.set("level", level);
      setData(await adminApi.get<Paged<ActivityRow>>(`/admin/activity?${params}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [page, search, level]);

  useEffect(() => {
    const iv = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(iv);
  }, [load, search]);

  return (
    <div className="space-y-4">
      {error && <ErrorBanner message={error} />}
      <AdminCard>
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 p-4 dark:border-slate-800">
          <AdminSearchInput value={search} onChange={(v) => { setSearch(v); setPage(1); }} placeholder={t("admin.common.search")} />
          <AdminSelect
            value={level}
            onChange={(v) => { setLevel(v); setPage(1); }}
            options={[
              { value: "all", label: t("admin.common.all") },
              { value: "INFO", label: "INFO" },
              { value: "WARNING", label: "WARNING" },
              { value: "ERROR", label: "ERROR" },
              { value: "CRITICAL", label: "CRITICAL" },
            ]}
          />
        </div>
        <AdminTable
          head={
            <>
              <Th>{t("admin.activity.level")}</Th>
              <Th>{t("admin.activity.event")}</Th>
              <Th>{t("admin.activity.message")}</Th>
              <Th>{t("admin.activity.account")}</Th>
              <Th>{t("admin.common.lastActivity")}</Th>
            </>
          }
        >
          {!data && <EmptyRow colSpan={5} label={t("common.loading")} />}
          {data && data.items.length === 0 && <EmptyRow colSpan={5} label={t("admin.common.none")} />}
          {data?.items.map((a) => (
            <tr key={a.id} className="transition-colors hover:bg-slate-50/60 dark:hover:bg-slate-800/40">
              <Td><AdminStatusBadge status={a.level} /></Td>
              <Td className="text-xs font-medium text-slate-600 dark:text-slate-300">{a.event_type}</Td>
              <Td className="max-w-md text-sm text-slate-700 dark:text-slate-200">
                <span className="line-clamp-2">{a.message}</span>
              </Td>
              <Td className="text-xs text-slate-400">{a.account_id ?? "—"}</Td>
              <Td className="text-xs text-slate-400">{formatTime(a.created_at)}</Td>
            </tr>
          ))}
        </AdminTable>
        {data && <AdminPagination page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />}
      </AdminCard>
    </div>
  );
}
