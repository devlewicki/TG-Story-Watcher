"use client";

import { useCallback, useEffect, useState } from "react";
import { adminApi, type WorkerStatus } from "@/lib/adminApi";
import { useTranslation } from "@/lib/i18n";
import { AdminCard, AdminCardHeader, ConfirmDialog, ErrorBanner, HealthDot, ProgressBar } from "@/components/admin/adminUi";

export default function AdminWorkerPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<WorkerStatus | null>(null);
  const [error, setError] = useState("");
  const [confirmRestart, setConfirmRestart] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setError("");
      setStatus(await adminApi.get<WorkerStatus>("/admin/worker"));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
    const iv = setInterval(load, 5000);
    return () => clearInterval(iv);
  }, [load]);

  async function control(path: string) {
    setBusy(true);
    try {
      await adminApi.post(path);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const uptime = (s: number | null) => {
    if (s == null) return "—";
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  };

  return (
    <div className="space-y-4">
      {error && <ErrorBanner message={error} />}

      <AdminCard>
        <AdminCardHeader
          title={t("admin.worker.title")}
          right={
            <div className="flex items-center gap-2">
              <HealthDot ok={status?.running ?? null} label={status?.paused ? t("admin.common.paused") : undefined} />
            </div>
          }
        />
        <dl className="grid grid-cols-2 gap-4 p-5 text-sm md:grid-cols-3">
          <div>
            <dt className="text-xs text-slate-400">{t("admin.worker.status")}</dt>
            <dd className="font-medium text-slate-800 dark:text-slate-100">
              {status == null ? "—" : status.paused ? t("admin.common.paused") : status.running ? t("admin.common.running") : t("admin.common.stopped")}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-400">{t("admin.worker.pid")}</dt>
            <dd className="font-medium text-slate-800 dark:text-slate-100">{status?.pid ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-400">{t("admin.worker.uptime")}</dt>
            <dd className="font-medium text-slate-800 dark:text-slate-100">{uptime(status?.uptime_seconds ?? null)}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-400">{t("admin.worker.heartbeat")}</dt>
            <dd className="font-medium text-slate-800 dark:text-slate-100">
              {status?.heartbeat_age != null ? t("admin.worker.ago", { n: Math.round(status.heartbeat_age) }) : "—"}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-400">{t("admin.worker.processed")}</dt>
            <dd className="font-medium text-slate-800 dark:text-slate-100">{status?.views_today ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-400">{t("admin.worker.queue")}</dt>
            <dd className="font-medium text-slate-800 dark:text-slate-100">{status?.queue_active ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-400">{t("admin.worker.errors")}</dt>
            <dd className={`font-medium ${(status?.consecutive_errors ?? 0) > 0 ? "text-red-500" : "text-slate-800 dark:text-slate-100"}`}>
              {status?.consecutive_errors ?? "—"}
            </dd>
          </div>
        </dl>
        <div className="flex flex-wrap gap-2 border-t border-slate-100 p-5 dark:border-slate-800">
          {status?.paused ? (
            <button
              disabled={busy}
              onClick={() => control("/admin/worker/resume")}
              className="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-700 disabled:opacity-50"
            >
              {t("admin.worker.resume")}
            </button>
          ) : (
            <button
              disabled={busy}
              onClick={() => control("/admin/worker/pause")}
              className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              {t("admin.worker.pause")}
            </button>
          )}
          <button
            disabled={busy}
            onClick={() => setConfirmRestart(true)}
            className="rounded-xl border border-amber-300 px-4 py-2 text-sm font-medium text-amber-700 transition-colors hover:bg-amber-50 disabled:opacity-50 dark:border-amber-500/40 dark:text-amber-400 dark:hover:bg-amber-500/10"
          >
            {t("admin.worker.restart")}
          </button>
        </div>
      </AdminCard>

      <ConfirmDialog
        open={confirmRestart}
        title={t("admin.worker.restart")}
        message={t("admin.worker.restartHint")}
        onConfirm={() => control("/admin/worker/restart")}
        onClose={() => setConfirmRestart(false)}
      />
    </div>
  );
}
