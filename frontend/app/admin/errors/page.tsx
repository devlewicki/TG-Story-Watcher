"use client";

import { useCallback, useEffect, useState } from "react";
import { adminApi, type ErrorGroupRow, type Paged } from "@/lib/adminApi";
import { useTranslation } from "@/lib/i18n";
import { formatTime } from "@/lib/format";
import {
  AdminCard,
  AdminPagination,
  AdminSearchInput,
  AdminStatusBadge,
  AdminTable,
  EmptyRow,
  ErrorBanner,
  Td,
  Th,
} from "@/components/admin/adminUi";

export default function AdminErrorsPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<Paged<ErrorGroupRow> | null>(null);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      const params = new URLSearchParams({ page: String(page), page_size: "30" });
      if (search) params.set("search", search);
      setData(await adminApi.get<Paged<ErrorGroupRow>>(`/admin/errors?${params}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [page, search]);

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
        </div>
        <AdminTable
          head={
            <>
              <Th>{t("admin.activity.level")}</Th>
              <Th>{t("admin.errors.message")}</Th>
              <Th>{t("admin.errors.count")}</Th>
              <Th>{t("admin.errors.firstSeen")}</Th>
              <Th>{t("admin.errors.lastSeen")}</Th>
            </>
          }
        >
          {!data && <EmptyRow colSpan={5} label={t("common.loading")} />}
          {data && data.items.length === 0 && <EmptyRow colSpan={5} label={t("admin.common.none")} />}
          {data?.items.map((e, idx) => {
            const key = `${e.message.slice(0, 40)}-${idx}`;
            return (
              <tr
                key={key}
                onClick={() => setExpanded(expanded === key ? null : key)}
                className="cursor-pointer transition-colors hover:bg-slate-50/60 dark:hover:bg-slate-800/40"
              >
                <Td><AdminStatusBadge status={e.level} /></Td>
                <Td className="max-w-md">
                  <span className={`text-sm text-slate-700 dark:text-slate-200 ${expanded === key ? "" : "line-clamp-2"}`}>{e.message}</span>
                  {e.event_type ? <span className="block text-xs text-slate-400">{e.event_type}</span> : null}
                </Td>
                <Td>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${(e.count ?? 0) > 10 ? "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-400" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"}`}>
                    {e.count}
                  </span>
                </Td>
                <Td className="text-xs text-slate-400">{formatTime(e.first_seen)}</Td>
                <Td className="text-xs text-slate-400">{formatTime(e.last_seen)}</Td>
              </tr>
            );
          })}
        </AdminTable>
        {data && <AdminPagination page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />}
      </AdminCard>
    </div>
  );
}
