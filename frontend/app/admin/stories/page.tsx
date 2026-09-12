"use client";

import { useCallback, useEffect, useState } from "react";
import { adminApi, type AdminStoryRow, type Paged } from "@/lib/adminApi";
import { useTranslation } from "@/lib/i18n";
import { formatTime } from "@/lib/format";
import {
  AdminCard,
  AdminPagination,
  AdminSearchInput,
  AdminSelect,
  AdminTable,
  EmptyRow,
  ErrorBanner,
  Td,
  Th,
} from "@/components/admin/adminUi";

export default function AdminStoriesPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<Paged<AdminStoryRow> | null>(null);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [source, setSource] = useState("all");
  const [viewed, setViewed] = useState("all");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const params = new URLSearchParams({ page: String(page), page_size: "25" });
      if (search) params.set("search", search);
      if (source !== "all") params.set("source", source);
      if (viewed !== "all") params.set("viewed", viewed);
      setData(await adminApi.get<Paged<AdminStoryRow>>(`/admin/stories?${params}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [page, search, source, viewed]);

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
            value={source}
            onChange={(v) => { setSource(v); setPage(1); }}
            options={[
              { value: "all", label: t("admin.common.all") },
              { value: "monitor", label: "monitor" },
              { value: "discovery", label: "discovery" },
              { value: "manual", label: "manual" },
            ]}
          />
          <AdminSelect
            value={viewed}
            onChange={(v) => { setViewed(v); setPage(1); }}
            options={[
              { value: "all", label: t("admin.common.all") },
              { value: "true", label: t("admin.common.yes") },
              { value: "false", label: t("admin.common.no") },
            ]}
          />
        </div>
        <AdminTable
          head={
            <>
              <Th>{t("admin.stories.author")}</Th>
              <Th>{t("admin.common.owner")}</Th>
              <Th>{t("admin.accounts.account")}</Th>
              <Th>{t("admin.dashboard.viewsToday")}</Th>
              <Th>{t("admin.common.created")}</Th>
            </>
          }
        >
          {!data && <EmptyRow colSpan={5} label={t("common.loading")} />}
          {data && data.items.length === 0 && <EmptyRow colSpan={5} label={t("admin.common.none")} />}
          {data?.items.map((s) => (
            <tr key={s.id} className="transition-colors hover:bg-slate-50/60 dark:hover:bg-slate-800/40">
              <Td>
                <span className="text-sm font-medium text-slate-800 dark:text-slate-100">
                  {s.author_username ? `@${s.author_username}` : s.author_name || `#${s.peer_id}`}
                </span>
                <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] uppercase text-slate-400 dark:bg-slate-800">{s.source}</span>
              </Td>
              <Td className="text-xs text-slate-500 dark:text-slate-400">{s.owner?.email || t("admin.common.none")}</Td>
              <Td className="text-xs text-slate-500 dark:text-slate-400">{s.account_username ? `@${s.account_username}` : s.account_id}</Td>
              <Td>{s.views}</Td>
              <Td className="text-xs text-slate-400">{formatTime(s.discovered_at)}</Td>
            </tr>
          ))}
        </AdminTable>
        {data && <AdminPagination page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />}
      </AdminCard>
    </div>
  );
}
