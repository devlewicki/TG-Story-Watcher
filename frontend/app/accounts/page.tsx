"use client";

import { useState } from "react";
import { api, type Account, clearToken } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { useTranslation } from "@/lib/i18n";
import { Badge, Button, Card, Empty, ErrorBanner, Icon, PageHeader, PageLoading } from "@/components/ui";
import { TelegramAuthModal } from "@/components/TelegramAuthModal";
import { timeAgo } from "@/lib/format";
import { friendlyError } from "@/lib/errors";

export default function AccountsPage() {
  const { t } = useTranslation();
  const { data, loading, error, refresh } = useFetch<Account[]>((s) =>
    api.get<Account[]>("/accounts", s)
  );

  const [showModal, setShowModal] = useState(false);

  if (loading) return <PageLoading />;
  if (error) return <ErrorBanner message={error} />;
  const accounts = data ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("accounts.title")}
        subtitle={t("accounts.subtitle")}
        right={
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={refresh}>
              <Icon name="refresh" className="h-4 w-4" />
              {t("common.refresh")}
            </Button>
            <Button onClick={() => setShowModal(true)}>
              <Icon name="send" className="h-4 w-4" />
              {t("common.add")}
            </Button>
            <Button variant="danger" onClick={() => { clearToken(); window.dispatchEvent(new Event("storywatcher:unauthorized")); }}>
              {t("common.logout")}
            </Button>
          </div>
        }
      />

      {accounts.length === 0 ? (
        <Card><Empty label={t("accounts.noAccounts")} /></Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {accounts.map((a) => (
            <AccountCard key={a.id} account={a} onChanged={refresh} />
          ))}
        </div>
      )}

      {showModal && <TelegramAuthModal onClose={() => setShowModal(false)} onDone={() => { setShowModal(false); refresh(); window.dispatchEvent(new Event("storywatcher:account-updated")); }} />}
    </div>
  );
}

function AccountCard({ account, onChanged }: { account: Account; onChanged: () => void }) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState<string | null>(null);
  const [showRelogin, setShowRelogin] = useState(false);
  const [actionError, setActionError] = useState("");
  const fullName = [account.first_name, account.last_name].filter(Boolean).join(" ");
  const name = fullName || account.username || account.phone;

  const act = async (kind: "start" | "pause") => {
    setBusy(kind);
    setActionError("");
    try {
      await api.post(`/accounts/${account.id}/${kind}`);
      onChanged();
    } catch (e) {
      setActionError(friendlyError(e));
    }
    setBusy(null);
  };

  const toggleMonitoring = async () => {
    setBusy("monitoring");
    setActionError("");
    try {
      await api.post(`/accounts/${account.id}/monitoring`, { monitoring: !account.monitoring });
      onChanged();
    } catch (e) {
      setActionError(friendlyError(e));
    }
    setBusy(null);
  };

  const remove = async () => {
    if (!confirm(t("accounts.deleteConfirm", { name }))) return;
    setBusy("delete");
    setActionError("");
    try {
      await api.delete(`/accounts/${account.id}`);
      onChanged();
    } catch (e) {
      setActionError(friendlyError(e));
    }
    setBusy(null);
  };

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between">
        <div>
          <div className="font-medium text-slate-900 dark:text-slate-50">{name}</div>
          <div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
            {account.phone}
            {fullName ? ` · ${fullName}` : ""}
            {account.username ? <> · <a href={`https://t.me/${account.username}`} target="_blank" rel="noopener noreferrer" className="text-emerald-600 hover:underline dark:text-emerald-400">@{account.username}</a></> : ""}
            {account.telegram_user_id ? ` · id ${account.telegram_user_id}` : ""}
          </div>
        </div>
        <Badge status={account.status} />
      </div>

      <div className="mt-3 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
        <span>{t("accounts.monitoringLabel")}: <b>{account.monitoring ? t("dashboard.on") : t("dashboard.off")}</b></span>
        <span>{t("accounts.lastSeen")} {timeAgo(account.last_seen_at)}</span>
      </div>

      {account.status === "AUTH_REQUIRED" && (
        <div className="mt-3 rounded-lg border border-orange-200 bg-orange-50 p-3 dark:border-orange-800 dark:bg-orange-500/10">
          <p className="text-sm font-medium text-orange-800 dark:text-orange-300">{t("accounts.reloginNeeded")}</p>
          <p className="mt-0.5 text-xs text-orange-600 dark:text-orange-400">{t("accounts.reloginDesc")}</p>
          <Button
            className="mt-2 !px-2.5 !py-1 !text-xs"
            onClick={() => setShowRelogin(true)}
          >
            {t("accounts.reloginButton")}
          </Button>
        </div>
      )}

      <div className="mt-3 grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
        {account.status !== "ACTIVE" ? (
          <Button variant="secondary" disabled={busy !== null} onClick={() => act("start")}>
            {busy === "start" ? "…" : t("accounts.start")}
          </Button>
        ) : (
          <Button variant="secondary" disabled={busy !== null} onClick={() => act("pause")}>
            {busy === "pause" ? "…" : t("accounts.pause")}
          </Button>
        )}
        <Button
          variant={account.monitoring ? "danger" : "secondary"}
          disabled={busy !== null}
          onClick={toggleMonitoring}
        >
          {t("accounts.monitoringToggle")} {account.monitoring ? t("dashboard.off") : t("dashboard.on")}
        </Button>
        <Button variant="danger" disabled={busy !== null} onClick={remove} className="col-span-2 sm:col-span-1 sm:ml-auto">
          {busy === "delete" ? "…" : t("common.delete")}
        </Button>
      </div>

      {actionError && (
        <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          {actionError}
        </div>
      )}

      {showRelogin && (
        <TelegramAuthModal
          onClose={() => setShowRelogin(false)}
          onDone={() => { setShowRelogin(false); onChanged(); }}
          initialPhone={account.phone}
          autoSend={true}
        />
      )}
    </Card>
  );
}

