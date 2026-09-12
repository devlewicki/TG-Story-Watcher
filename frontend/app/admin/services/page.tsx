"use client";

import { useCallback, useEffect, useState } from "react";
import { adminApi, type ServiceRow } from "@/lib/adminApi";
import { useTranslation } from "@/lib/i18n";
import { AdminCard, AdminCardHeader, ErrorBanner, HealthDot, AdminTable, EmptyRow, Td, Th } from "@/components/admin/adminUi";

const NAME_KEYS: Record<string, string> = {
  backend: "admin.services.backend",
  worker: "admin.services.worker",
  postgres: "admin.services.postgres",
  redis: "admin.services.redis",
  frontend: "admin.services.frontend",
  nginx: "admin.services.nginx",
  vpn_proxy: "admin.services.vpnProxy",
};

export default function AdminServicesPage() {
  const { t } = useTranslation();
  const [services, setServices] = useState<ServiceRow[] | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setError("");
      const res = await adminApi.get<{ services: ServiceRow[] }>("/admin/services");
      setServices(res.services);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
    const iv = setInterval(load, 15000);
    return () => clearInterval(iv);
  }, [load]);

  return (
    <div className="space-y-4">
      {error && <ErrorBanner message={error} />}
      <AdminCard>
        <AdminCardHeader title={t("admin.services.title")} />
        <AdminTable
          head={
            <>
              <Th>{t("admin.services.title")}</Th>
              <Th>{t("admin.common.status")}</Th>
              <Th>{t("admin.services.version")}</Th>
              <Th>{t("admin.services.uptime")}</Th>
              <Th>{t("admin.services.lastCheck")}</Th>
            </>
          }
        >
          {!services && <EmptyRow colSpan={5} label={t("common.loading")} />}
          {services?.map((s) => (
            <tr key={s.name} className="transition-colors hover:bg-slate-50/60 dark:hover:bg-slate-800/40">
              <Td className="font-medium text-slate-800 dark:text-slate-100">{t(NAME_KEYS[s.name] || s.name)}</Td>
              <Td><HealthDot ok={s.ok} label={s.paused ? t("admin.common.paused") : undefined} /></Td>
              <Td className="text-xs text-slate-400">{s.version || "—"}</Td>
              <Td className="text-xs text-slate-400">
                {s.uptime_seconds != null ? `${Math.floor(s.uptime_seconds / 3600)}h ${Math.floor((s.uptime_seconds % 3600) / 60)}m` : "—"}
              </Td>
              <Td className="text-xs text-slate-400">{s.last_check ? new Date(s.last_check).toLocaleTimeString() : "—"}</Td>
            </tr>
          ))}
        </AdminTable>
      </AdminCard>
    </div>
  );
}
