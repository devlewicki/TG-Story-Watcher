"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { adminApi, type BackupOperation, type BackupRow, type Paged } from "@/lib/adminApi";
import { useTranslation } from "@/lib/i18n";
import { formatTime } from "@/lib/format";
import {
  AdminCard,
  AdminCardHeader,
  AdminStatusBadge,
  AdminTable,
  ConfirmDialog,
  EmptyRow,
  ErrorBanner,
  ProgressBar,
  Td,
  Th,
} from "@/components/admin/adminUi";

function fmtSize(bytes: number) {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export default function AdminBackupsPage() {
  const { t } = useTranslation();
  const [list, setList] = useState<Paged<BackupRow> | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // create form
  const [createOpen, setCreateOpen] = useState(false);
  const [encrypt, setEncrypt] = useState(false);
  const [password, setPassword] = useState("");

  // operation progress
  const [op, setOp] = useState<BackupOperation | null>(null);
  const opPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // validate dialog
  const [validateTarget, setValidateTarget] = useState<BackupRow | null>(null);
  const [validatePassword, setValidatePassword] = useState("");
  const [validateResult, setValidateResult] = useState<Record<string, unknown> | null>(null);

  // restore dialog
  const [restoreTarget, setRestoreTarget] = useState<BackupRow | null>(null);
  const [restorePassword, setRestorePassword] = useState("");
  const [restoreTyped, setRestoreTyped] = useState("");
  const [preRestore, setPreRestore] = useState(true);
  // restore result (survives the DB replacement via storage metadata)
  const [restoreResult, setRestoreResult] = useState<Record<string, unknown> | null>(null);

  // delete dialog
  const [deleteTarget, setDeleteTarget] = useState<BackupRow | null>(null);

  // upload
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  // settings
  const [auto, setAuto] = useState({ enabled: false, schedule_hour_utc: 4, retention: 7, encrypted: false });
  const [retentionKeep, setRetentionKeep] = useState(7);

  const load = useCallback(async () => {
    try {
      setError("");
      setList(await adminApi.get<Paged<BackupRow>>("/admin/backups?page_size=50"));
      const s = await adminApi.get<{ auto_backup: typeof auto }>("/admin/backups/settings");
      if (s.auto_backup && Object.keys(s.auto_backup).length) setAuto({ ...auto, ...s.auto_backup });
    } catch (e) {
      setError((e as Error).message);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Poll the latest operation while it is running.
  const startOpPolling = useCallback((opId: string) => {
    if (opPollRef.current) clearInterval(opPollRef.current);
    opPollRef.current = setInterval(async () => {
      try {
        const cur = await adminApi.get<BackupOperation>(`/admin/backups/operations/${opId}`);
        setOp(cur);
        if (cur.status === "SUCCESS" || cur.status === "FAILED") {
          if (opPollRef.current) clearInterval(opPollRef.current);
          opPollRef.current = null;
          if (cur.status === "SUCCESS" && cur.type === "CREATE") setNotice(t("admin.common.saved"));
          if (cur.type === "RESTORE") setRestoreResult((cur.result as Record<string, unknown> | null) ?? null);
          load();
        }
      } catch {
        // Restored DB may have replaced admin tables — the result is served
        // from storage metadata; fetch it once more before giving up.
        if (opPollRef.current) clearInterval(opPollRef.current);
        opPollRef.current = null;
        try {
          const cur = await adminApi.get<BackupOperation>(`/admin/backups/operations/${opId}`);
          if (cur.type === "RESTORE") setRestoreResult((cur.result as Record<string, unknown> | null) ?? null);
        } catch {
          /* operation truly unknown */
        }
      }
    }, 1500);
  }, [load, t]);

  useEffect(() => () => {
    if (opPollRef.current) clearInterval(opPollRef.current);
  }, []);

  async function createBackup() {
    try {
      const res = await adminApi.post<{ operation_id: string }>("/admin/backups", {
        password: encrypt ? password : null,
      });
      setCreateOpen(false);
      setPassword("");
      setOp({ id: res.operation_id, type: "CREATE", status: "RUNNING", progress: 5, backup_id: null, stage: null, result: null, started_at: null, finished_at: null, error: null, created_by: null });
      startOpPolling(res.operation_id);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function runValidate() {
    if (!validateTarget) return;
    try {
      const res = await adminApi.post<{ operation_id: string }>(`/admin/backups/${validateTarget.id}/validate`, {
        password: validatePassword || null,
      });
      setValidateResult(null);
      startOpPolling(res.operation_id);
      // One-shot fetch of the result when it finishes
      const check = setInterval(async () => {
        try {
          const cur = await adminApi.get<BackupOperation>(`/admin/backups/operations/${res.operation_id}`);
          if (cur.status === "SUCCESS") {
            setValidateResult(cur.result);
            clearInterval(check);
          } else if (cur.status === "FAILED") {
            setError(cur.error || "Validation failed");
            clearInterval(check);
          }
        } catch {
          clearInterval(check);
        }
      }, 1500);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function runRestore() {
    if (!restoreTarget || restoreTyped !== "RESTORE") return;
    try {
      const res = await adminApi.post<{ operation_id: string }>(`/admin/backups/${restoreTarget.id}/restore`, {
        password: restorePassword || null,
        confirm: "RESTORE",
        create_pre_restore_backup: preRestore,
      });
      setRestoreTarget(null);
      setRestoreTyped("");
      setRestoreResult(null);
      setNotice(t("admin.backups.restoreHint"));
      setOp({ id: res.operation_id, type: "RESTORE", status: "RUNNING", progress: 5, backup_id: restoreTarget.id, stage: null, result: null, started_at: null, finished_at: null, error: null, created_by: null });
      startOpPolling(res.operation_id);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function uploadFile(f: File) {
    setUploading(true);
    setError("");
    try {
      const token = typeof window !== "undefined" ? localStorage.getItem("storywatcher_admin_token") : null;
      const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:9000/api";
      const res = await fetch(`${base}/admin/backups/upload`, {
        method: "POST",
        headers: token ? { "X-Admin-Token": token } : {},
        body: (() => {
          const fd = new FormData();
          fd.append("file", f);
          return fd;
        })(),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Upload failed (${res.status})`);
      }
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  async function saveAutoSettings(next: typeof auto) {
    setAuto(next);
    try {
      await adminApi.put("/admin/backups/settings", next);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="space-y-4">
      {error && <ErrorBanner message={error} />}
      {notice && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
          {notice}
        </div>
      )}

      {/* Running operation */}
      {op && op.status !== "SUCCESS" && op.status !== "FAILED" && (
        <AdminCard className="p-5">
          <div className="mb-2 flex items-center justify-between text-sm">
            <span className="font-medium text-slate-800 dark:text-slate-100">
              {t("admin.backups.operation")}: {op.type}
            </span>
            <span className="text-slate-400">{op.progress}%</span>
          </div>
          <ProgressBar value={op.progress} />
          {op.stage && <p className="mt-2 text-xs text-slate-400">{op.stage}</p>}
        </AdminCard>
      )}

      {/* Restore report (TZ §35) */}
      {restoreResult && (
        <AdminCard className="p-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{t("admin.backups.restoreReport")}</h3>
            <AdminStatusBadge status={String(restoreResult.status ?? "SUCCESS")} />
          </div>
          <dl className="space-y-1.5 text-sm">
            <div className="flex justify-between"><dt className="text-slate-400">{t("admin.backups.restoredUsers")}</dt><dd className="font-medium text-emerald-600 dark:text-emerald-400">{String(restoreResult.restored_users ?? "—")}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-400">{t("admin.backups.restoredAccounts")}</dt><dd className="font-medium text-emerald-600 dark:text-emerald-400">{String(restoreResult.restored_accounts ?? "—")}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-400">{t("admin.backups.restoredSessions")}</dt><dd className="font-medium text-emerald-600 dark:text-emerald-400">{String(restoreResult.restored_sessions ?? "—")}{restoreResult.expected_sessions != null ? ` / ${restoreResult.expected_sessions}` : ""}</dd></div>
            {Number(restoreResult.session_paths_repointed ?? 0) > 0 && (
              <div className="flex justify-between"><dt className="text-slate-400">{t("admin.backups.sessionsRepointed")}</dt><dd>{String(restoreResult.session_paths_repointed)}</dd></div>
            )}
          </dl>
          <p className="mt-3 text-xs text-amber-600 dark:text-amber-400">{t("admin.backups.workerPaused")}</p>
        </AdminCard>
      )}

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-2">
        <button onClick={() => setCreateOpen(true)} className="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-emerald-700">
          {t("admin.backups.create")}
        </button>
        <button
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
          className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          {uploading ? t("common.loading") : t("admin.backups.upload")}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".tar.gz,.gz,.enc"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) uploadFile(f);
            e.target.value = "";
          }}
        />
        <p className="text-xs text-slate-400">{t("admin.backups.uploadHint")}</p>
      </div>

      {/* List */}
      <AdminCard>
        <AdminCardHeader title={t("admin.backups.title")} subtitle={t("admin.backups.createHint")} />
        <AdminTable
          head={
            <>
              <Th>{t("admin.backups.created")}</Th>
              <Th>{t("admin.backups.version")}</Th>
              <Th>{t("admin.backups.users")}/{t("admin.backups.accounts")}/{t("admin.backups.sessions")}</Th>
              <Th>{t("admin.backups.size")}</Th>
              <Th>{t("admin.common.status")}</Th>
              <Th className="text-right">{t("admin.common.actions")}</Th>
            </>
          }
        >
          {!list && <EmptyRow colSpan={6} label={t("common.loading")} />}
          {list && list.items.length === 0 && <EmptyRow colSpan={6} label={t("admin.common.none")} />}
          {list?.items.map((b) => (
            <tr key={b.id} className="transition-colors hover:bg-slate-50/60 dark:hover:bg-slate-800/40">
              <Td>
                <span className="block text-sm font-medium text-slate-800 dark:text-slate-100">{formatTime(b.created_at)}</span>
                <span className="block max-w-[200px] truncate text-xs text-slate-400" title={b.filename}>{b.filename}</span>
              </Td>
              <Td className="text-xs text-slate-400">{b.application_version || "—"}</Td>
              <Td className="text-xs text-slate-500 dark:text-slate-300">
                {b.users ?? "—"} / {b.accounts ?? "—"} / {b.sessions ?? "—"}
              </Td>
              <Td className="text-xs text-slate-400">
                {fmtSize(b.size)} {b.encrypted ? `· ${t("admin.backups.encrypted")}` : ""}
              </Td>
              <Td><AdminStatusBadge status={b.status} /></Td>
              <Td>
                <div className="flex justify-end gap-1">
                  <a
                    href={`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:9000/api"}/admin/backups/${b.id}/download`}
                    onClick={async (e) => {
                      // Fetch with auth header to avoid token-less direct link issues.
                      e.preventDefault();
                      try {
                        const token = localStorage.getItem("storywatcher_admin_token");
                        const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:9000/api";
                        const res = await fetch(`${base}/admin/backups/${b.id}/download`, {
                          headers: token ? { "X-Admin-Token": token } : {},
                        });
                        if (!res.ok) throw new Error(`Download failed (${res.status})`);
                        const blob = await res.blob();
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = b.filename;
                        a.click();
                        URL.revokeObjectURL(url);
                      } catch (err) {
                        setError((err as Error).message);
                      }
                    }}
                    className="rounded-lg px-2 py-1 text-xs text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-500/10"
                  >
                    {t("admin.backups.download")}
                  </a>
                  <button onClick={() => { setValidateTarget(b); setValidateResult(null); setValidatePassword(""); }} className="rounded-lg px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">
                    {t("admin.backups.validate")}
                  </button>
                  <button onClick={() => { setRestoreTarget(b); setRestoreTyped(""); setRestorePassword(""); }} className="rounded-lg px-2 py-1 text-xs text-amber-600 hover:bg-amber-50 dark:hover:bg-amber-500/10">
                    {t("admin.backups.restore")}
                  </button>
                  <button onClick={() => setDeleteTarget(b)} className="rounded-lg px-2 py-1 text-xs text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10">
                    {t("admin.common.delete")}
                  </button>
                </div>
              </Td>
            </tr>
          ))}
        </AdminTable>
      </AdminCard>

      {/* Settings: retention + auto backup */}
      <div className="grid gap-4 md:grid-cols-2">
        <AdminCard>
          <AdminCardHeader title={t("admin.backups.retention")} subtitle={t("admin.backups.retentionHint")} />
          <div className="flex items-center gap-2 p-5">
            <input
              type="number"
              min={1}
              max={100}
              value={retentionKeep}
              onChange={(e) => setRetentionKeep(Number(e.target.value))}
              className="w-24 rounded-xl border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-white"
            />
            <button
              onClick={async () => {
                try {
                  await adminApi.post("/admin/backups/retention", { keep: retentionKeep });
                  load();
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
              className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              {t("admin.backups.applyRetention")}
            </button>
          </div>
        </AdminCard>
        <AdminCard>
          <AdminCardHeader title={t("admin.backups.autoBackup")} />
          <div className="space-y-3 p-5 text-sm">
            <label className="flex items-center justify-between">
              <span className="text-slate-600 dark:text-slate-300">{t("admin.backups.enabled")}</span>
              <input type="checkbox" checked={auto.enabled} onChange={(e) => saveAutoSettings({ ...auto, enabled: e.target.checked })} className="h-4 w-4 accent-emerald-600" />
            </label>
            <label className="flex items-center justify-between gap-3">
              <span className="text-slate-600 dark:text-slate-300">{t("admin.backups.schedule")}</span>
              <input
                type="number"
                min={0}
                max={23}
                value={auto.schedule_hour_utc}
                onChange={(e) => saveAutoSettings({ ...auto, schedule_hour_utc: Number(e.target.value) })}
                className="w-20 rounded-xl border border-slate-300 px-3 py-1.5 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
              />
            </label>
            <label className="flex items-center justify-between gap-3">
              <span className="text-slate-600 dark:text-slate-300">{t("admin.backups.retentionCount")}</span>
              <input
                type="number"
                min={1}
                max={100}
                value={auto.retention}
                onChange={(e) => saveAutoSettings({ ...auto, retention: Number(e.target.value) })}
                className="w-20 rounded-xl border border-slate-300 px-3 py-1.5 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
              />
            </label>
            <label className="flex items-center justify-between">
              <span className="text-slate-600 dark:text-slate-300">{t("admin.backups.autoEncrypted")}</span>
              <input type="checkbox" checked={auto.encrypted} onChange={(e) => saveAutoSettings({ ...auto, encrypted: e.target.checked })} className="h-4 w-4 accent-emerald-600" />
            </label>
          </div>
        </AdminCard>
      </div>

      {/* Create dialog */}
      <ConfirmDialog
        open={createOpen}
        title={t("admin.backups.create")}
        message={
          <span>
            {t("admin.backups.createHint")}
            <label className="mt-3 flex items-center gap-2 text-sm">
              <input type="checkbox" checked={encrypt} onChange={(e) => setEncrypt(e.target.checked)} className="h-4 w-4 accent-emerald-600" />
              {t("admin.backups.encrypt")}
            </label>
            {encrypt && (
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={t("admin.backups.password")}
                className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-white"
              />
            )}
            {encrypt && <span className="mt-1 block text-xs text-amber-600 dark:text-amber-400">{t("admin.backups.passwordHint")}</span>}
          </span>
        }
        confirmLabel={t("admin.backups.create")}
        onConfirm={createBackup}
        onClose={() => setCreateOpen(false)}
      />

      {/* Validate dialog */}
      {validateTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" onClick={() => setValidateTarget(null)} />
          <div className="relative max-h-[85vh] w-full max-w-md overflow-y-auto rounded-2xl border border-slate-200 bg-white p-5 shadow-xl dark:border-slate-700 dark:bg-slate-900 sm:p-6">
            <h3 className="text-base font-semibold text-slate-900 dark:text-white">{t("admin.backups.validating")}</h3>
            {validateTarget.encrypted && (
              <input
                type="password"
                value={validatePassword}
                onChange={(e) => setValidatePassword(e.target.value)}
                placeholder={t("admin.backups.password")}
                className="mt-3 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-white"
              />
            )}
            <button onClick={runValidate} className="mt-3 w-full rounded-xl bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700">
              {t("admin.backups.validate")}
            </button>
            {validateResult && (
              <dl className="mt-4 space-y-1.5 text-sm">
                <div className="flex justify-between"><dt className="text-slate-400">{t("admin.backups.integrity")}</dt><dd className="text-emerald-600 dark:text-emerald-400">{String(validateResult.integrity)}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-400">{t("admin.backups.database")}</dt><dd className="text-emerald-600 dark:text-emerald-400">{String(validateResult.database)}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-400">{t("admin.backups.sessions")}</dt><dd>{t("admin.backups.sessionsFound", { n: Number(validateResult.sessions ?? 0) })}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-400">{t("admin.backups.compatibility")}</dt><dd className="text-emerald-600 dark:text-emerald-400">{t("admin.backups.compatible")}</dd></div>
              </dl>
            )}
          </div>
        </div>
      )}

      {/* Restore dialog */}
      <ConfirmDialog
        open={!!restoreTarget}
        title={t("admin.backups.restoreConfirmTitle")}
        message={
          <span>
            <span className="block rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
              {t("admin.backups.restoreWarning")}
            </span>
            <label className="mt-3 flex items-center gap-2 text-sm">
              <input type="checkbox" checked={preRestore} onChange={(e) => setPreRestore(e.target.checked)} className="h-4 w-4 accent-emerald-600" />
              {t("admin.backups.preRestore")}
            </label>
            {restoreTarget?.encrypted && (
              <input
                type="password"
                value={restorePassword}
                onChange={(e) => setRestorePassword(e.target.value)}
                placeholder={t("admin.backups.password")}
                className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-white"
              />
            )}
            <span className="mt-3 block text-xs text-slate-400">{t("admin.backups.restoreTypeConfirm")}: RESTORE</span>
          </span>
        }
        requireText="RESTORE"
        danger
        confirmLabel={t("admin.backups.restore")}
        onConfirm={runRestore}
        onClose={() => setRestoreTarget(null)}
      />

      {/* Delete dialog */}
      <ConfirmDialog
        open={!!deleteTarget}
        title={t("admin.common.delete")}
        message={deleteTarget?.filename}
        danger
        confirmLabel={t("admin.common.delete")}
        onConfirm={() => deleteTarget && adminApi.delete(`/admin/backups/${deleteTarget.id}`).then(load)}
        onClose={() => setDeleteTarget(null)}
      />
    </div>
  );
}
