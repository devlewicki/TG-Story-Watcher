"use client";

import { useState } from "react";
import { api, type Account, clearToken } from "@/lib/api";
import { useFetch } from "@/lib/useFetch";
import { Badge, Button, Card, CardHeader, Empty, ErrorBanner, Spinner } from "@/components/ui";
import { timeAgo } from "@/lib/format";

type FlowStep = "phone" | "code" | "password";

export default function AccountsPage() {
  const { data, loading, error, refresh } = useFetch<Account[]>((s) =>
    api.get<Account[]>("/accounts", s)
  );

  const [showModal, setShowModal] = useState(false);

  if (loading) return <Spinner />;
  if (error) return <ErrorBanner message={error} />;
  const accounts = data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-semibold">Аккаунты</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">Подключённые Telegram-аккаунты</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={refresh}>↻ Обновить</Button>
          <Button onClick={() => setShowModal(true)}>＋ Добавить</Button>
          <Button variant="danger" onClick={() => { clearToken(); window.dispatchEvent(new Event("storywatcher:unauthorized")); }}>Выйти</Button>
        </div>
      </div>

      {accounts.length === 0 ? (
        <Card><Empty label="Аккаунтов пока нет. Добавьте аккаунт, чтобы подключить Telegram." /></Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {accounts.map((a) => (
            <AccountCard key={a.id} account={a} onChanged={refresh} />
          ))}
        </div>
      )}

      {showModal && <AuthModal onClose={() => setShowModal(false)} onDone={() => { setShowModal(false); refresh(); window.dispatchEvent(new Event("storywatcher:account-updated")); }} />}
    </div>
  );
}

function AccountCard({ account, onChanged }: { account: Account; onChanged: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const fullName = [account.first_name, account.last_name].filter(Boolean).join(" ");
  const name = fullName || account.username || account.phone;

  const act = async (kind: "start" | "pause") => {
    setBusy(kind);
    try {
      await api.post(`/accounts/${account.id}/${kind}`);
      onChanged();
    } catch (e) {
      alert((e as Error).message);
    }
    setBusy(null);
  };

  const toggleMonitoring = async () => {
    setBusy("monitoring");
    try {
      await api.post(`/accounts/${account.id}/monitoring`, { monitoring: !account.monitoring });
      onChanged();
    } catch (e) {
      alert((e as Error).message);
    }
    setBusy(null);
  };

  const remove = async () => {
    if (!confirm(`Удалить аккаунт ${name}? Telegram-сессия будет удалена.`)) return;
    setBusy("delete");
    try {
      await api.delete(`/accounts/${account.id}`);
      onChanged();
    } catch (e) {
      alert((e as Error).message);
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
            {account.username ? ` · @${account.username}` : ""}
            {account.telegram_user_id ? ` · id ${account.telegram_user_id}` : ""}
          </div>
        </div>
        <Badge status={account.status} />
      </div>

      <div className="mt-3 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
        <span>Мониторинг: <b>{account.monitoring ? "ВКЛ" : "ВЫКЛ"}</b></span>
        <span>Был в сети {timeAgo(account.last_seen_at)}</span>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:flex sm:flex-wrap">
        {account.status !== "ACTIVE" ? (
          <Button variant="secondary" disabled={busy !== null} onClick={() => act("start")}>
            {busy === "start" ? "…" : "▶ Запустить"}
          </Button>
        ) : (
          <Button variant="secondary" disabled={busy !== null} onClick={() => act("pause")}>
            {busy === "pause" ? "…" : "⏸ Пауза"}
          </Button>
        )}
        <Button
          variant={account.monitoring ? "danger" : "secondary"}
          disabled={busy !== null}
          onClick={toggleMonitoring}
        >
          Мониторинг {account.monitoring ? "ВЫКЛ" : "ВКЛ"}
        </Button>
        <Button variant="danger" disabled={busy !== null} onClick={remove} className="col-span-2 sm:col-span-1 sm:ml-auto">
          {busy === "delete" ? "…" : "Удалить"}
        </Button>
      </div>
    </Card>
  );
}

function AuthModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [step, setStep] = useState<FlowStep>("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const sendCode = async () => {
    setError("");
    if (phone.length < 5) return setError("Введите корректный номер телефона.");
    setBusy(true);
    try {
      await api.post("/auth/send-code", { phone });
      setStep("code");
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  };

  const confirmCode = async () => {
    setError("");
    setBusy(true);
    try {
      const res = await api.post<{ status: string; needs_password?: boolean }>("/auth/confirm-code", {
        phone,
        code,
      });
      if (res.status === "twofa") {
        setStep("password");
      } else {
        onDone();
      }
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  };

  const confirmPassword = async () => {
    setError("");
    setBusy(true);
    try {
      await api.post("/auth/confirm-password", { phone, password });
      onDone();
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  };

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-slate-900/50 p-4">
      <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Подключение Telegram</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">✕</button>
        </div>

        <div className="mt-4 flex items-center gap-1 text-xs text-slate-400">
          {(["phone", "code", "password"] as FlowStep[]).map((s, i) => (
            <span key={s} className="flex items-center gap-1">
              {i > 0 && <span>→</span>}
              <span className={step === s ? "text-emerald-600" : ""}>{stepLabel(s)}</span>
            </span>
          ))}
        </div>

        {step === "phone" && (
          <div className="mt-4">
            <label className="text-sm text-slate-600 dark:text-slate-300">Номер телефона</label>
            <input
              type="text"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+15551234567"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
              autoFocus
            />
          </div>
        )}

        {step === "code" && (
          <div className="mt-4">
            <label className="text-sm text-slate-600 dark:text-slate-300">
              Код подтверждения (отправлен в Telegram)
            </label>
            <input
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="12345"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
              autoFocus
            />
          </div>
        )}

        {step === "password" && (
          <div className="mt-4">
            <label className="text-sm text-slate-600 dark:text-slate-300">
              Пароль двухфакторной аутентификации
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Пароль 2FA"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
              autoFocus
            />
          </div>
        )}

        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Отмена</Button>
          {step === "phone" && (
            <Button onClick={sendCode} disabled={busy}>{busy ? "…" : "Отправить код"}</Button>
          )}
          {step === "code" && (
            <Button onClick={confirmCode} disabled={busy}>{busy ? "…" : "Подтвердить"}</Button>
          )}
          {step === "password" && (
            <Button onClick={confirmPassword} disabled={busy}>{busy ? "…" : "Войти"}</Button>
          )}
        </div>
      </div>
    </div>
  );
}

function stepLabel(s: FlowStep): string {
  return s === "phone" ? "Телефон" : s === "code" ? "Код" : "2FA";
}