"use client";

import { useCallback, useEffect, useState } from "react";
import { adminApi, type AdminSessionRow, type AuditLogRow, type Paged } from "@/lib/adminApi";
import { useTranslation } from "@/lib/i18n";
import { formatTime } from "@/lib/format";
import {
  AdminCard,
  AdminCardHeader,
  AdminPagination,
  AdminStatusBadge,
  AdminTable,
  ConfirmDialog,
  EmptyRow,
  ErrorBanner,
  Td,
  Th,
} from "@/components/admin/adminUi";

export default function AdminSecurityPage() {
  const { t } = useTranslation();
  const [sessions, setSessions] = useState<AdminSessionRow[] | null>(null);
  const [audit, setAudit] = useState<Paged<AuditLogRow> | null>(null);
  const [auditPage, setAuditPage] = useState(1);
  const [error, setError] = useState("");
  const [revokeAll, setRevokeAll] = useState(false);
  const [revokeOne, setRevokeOne] = useState<AdminSessionRow | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      const [s, a] = await Promise.all([
        adminApi.get<{ items: AdminSessionRow[] }>("/admin/security/sessions"),
        adminApi.get<Paged<AuditLogRow>>(`/admin/audit-logs?page=${auditPage}&page_size=25`),
      ]);
      setSessions(s.items);
      setAudit(a);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [auditPage]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-4">
      {error && <ErrorBanner message={error} />}

      <AdminCard>
        <AdminCardHeader
          title={t("admin.security.sessions")}
          right={
            <button onClick={() => setRevokeAll(true)} className="rounded-xl border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 dark:border-red-500/30 dark:hover:bg-red-500/10">
              {t("admin.security.revokeAll")}
            </button>
          }
        />
        <AdminTable
          head={
            <>
              <Th>{t("admin.security.admin")}</Th>
              <Th>{t("admin.security.ip")}</Th>
              <Th>{t("admin.security.userAgent")}</Th>
              <Th>{t("admin.common.created")}</Th>
              <Th>{t("admin.security.expires")}</Th>
              <Th className="text-right">{t("admin.common.actions")}</Th>
            </>
          }
        >
          {!sessions && <EmptyRow colSpan={6} label={t("common.loading")} />}
          {sessions && sessions.length === 0 && <EmptyRow colSpan={6} label={t("admin.common.none")} />}
          {sessions?.map((s) => (
            <tr key={s.id} className="transition-colors hover:bg-slate-50/60 dark:hover:bg-slate-800/40">
              <Td className="font-medium text-slate-800 dark:text-slate-100">{s.admin_username}</Td>
              <Td className="text-xs text-slate-500 dark:text-slate-400">{s.ip || "—"}</Td>
              <Td className="max-w-[220px] truncate text-xs text-slate-400"><span title={s.user_agent || ""}>{s.user_agent || "—"}</span></Td>
              <Td className="text-xs text-slate-400">{formatTime(s.created_at)}</Td>
              <Td className="text-xs text-slate-400">{formatTime(s.expires_at)}</Td>
              <Td className="text-right">
                <button onClick={() => setRevokeOne(s)} className="rounded-lg px-2 py-1 text-xs text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10">
                  {t("admin.security.revoke")}
                </button>
              </Td>
            </tr>
          ))}
        </AdminTable>
      </AdminCard>

      <AdminCard>
        <AdminCardHeader title={t("admin.security.auditLog")} />
        <AdminTable
          head={
            <>
              <Th>{t("admin.common.lastActivity")}</Th>
              <Th>{t("admin.security.admin")}</Th>
              <Th>{t("admin.security.action")}</Th>
              <Th>{t("admin.security.target")}</Th>
              <Th>{t("admin.security.result")}</Th>
              <Th>{t("admin.security.ip")}</Th>
            </>
          }
        >
          {!audit && <EmptyRow colSpan={6} label={t("common.loading")} />}
          {audit && audit.items.length === 0 && <EmptyRow colSpan={6} label={t("admin.common.none")} />}
          {audit?.items.map((a) => (
            <tr key={a.id} className="transition-colors hover:bg-slate-50/60 dark:hover:bg-slate-800/40">
              <Td className="text-xs text-slate-400">{formatTime(a.created_at)}</Td>
              <Td className="text-sm text-slate-700 dark:text-slate-200">{a.admin_username || "—"}</Td>
              <Td className="text-xs font-medium text-slate-600 dark:text-slate-300">{a.action}</Td>
              <Td className="text-xs text-slate-400">{a.target || "—"}</Td>
              <Td><AdminStatusBadge status={a.result === "SUCCESS" ? "SUCCESS" : "FAILED"} /></Td>
              <Td className="text-xs text-slate-400">{a.ip || "—"}</Td>
            </tr>
          ))}
        </AdminTable>
        {audit && <AdminPagination page={auditPage} pageSize={audit.page_size} total={audit.total} onPage={setAuditPage} />}
      </AdminCard>

      <ConfirmDialog
        open={revokeAll}
        title={t("admin.security.revokeAll")}
        danger
        onConfirm={async () => {
          try {
            await adminApi.post("/admin/security/sessions/revoke-all");
            load();
          } catch (e) {
            setError((e as Error).message);
          }
        }}
        onClose={() => setRevokeAll(false)}
      />
      <ConfirmDialog
        open={!!revokeOne}
        title={t("admin.security.revoke")}
        danger
        onConfirm={async () => {
          if (!revokeOne) return;
          try {
            await adminApi.post(`/admin/security/sessions/${revokeOne.id}/revoke`);
            load();
          } catch (e) {
            setError((e as Error).message);
          }
        }}
        onClose={() => setRevokeOne(null)}
      />
    </div>
  );
}
