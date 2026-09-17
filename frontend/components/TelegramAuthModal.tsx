"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import { Button, IconButton, Icon } from "@/components/ui";
import { friendlyError, validatePhone } from "@/lib/errors";

type FlowStep = "phone" | "code" | "password";

// Must match backend SEND_CODE_COOLDOWN (client_manager.py).
const SEND_CODE_COOLDOWN = 60;

export function TelegramAuthModal({
  onClose,
  onDone,
  initialPhone,
  autoSend,
}: {
  onClose: () => void;
  onDone: () => void;
  initialPhone?: string;
  autoSend?: boolean;
}) {
  const { t } = useTranslation();
  const [step, setStep] = useState<FlowStep>("phone");
  const [phone, setPhone] = useState(initialPhone ?? "");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [countdown, setCountdown] = useState(0);

  // Visible resend countdown so users don't hammer send-code (Telegram
  // exhausts a number's delivery options and rejects resends).
  useEffect(() => {
    if (countdown <= 0) return;
    const id = setInterval(() => setCountdown((c) => Math.max(0, c - 1)), 1000);
    return () => clearInterval(id);
  }, [countdown]);

  const doSendCode = async (targetPhone: string) => {
    setError("");
    setBusy(true);
    try {
      await api.post("/auth/send-code", { phone: targetPhone });
      setStep("code");
      setCountdown(SEND_CODE_COOLDOWN);
    } catch (e) {
      const err = e as ApiError;
      setError(friendlyError(err));
      if (err.status === 429) {
        const match = err.message.match(/(\d+)/);
        const secs = match
          ? Math.max(5, Math.min(SEND_CODE_COOLDOWN, parseInt(match[1], 10)))
          : SEND_CODE_COOLDOWN;
        setCountdown(secs);
      }
    }
    setBusy(false);
  };

  // Auto-send code on mount when opened in re-login mode.
  const autoSendHandled = useRef(false);
  useEffect(() => {
    if (initialPhone && autoSend && !autoSendHandled.current) {
      autoSendHandled.current = true;
      doSendCode(initialPhone);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const sendCode = async () => {
    setError("");
    const phoneErr = validatePhone(phone);
    if (phoneErr) return setError(phoneErr);
    await doSendCode(phone);
  };

  const confirmCode = async () => {
    setError("");
    if (!code.trim()) return setError(friendlyError(new Error(t("auth.authError"))));
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
      setError(friendlyError(e));
    }
    setBusy(false);
  };

  const confirmPassword = async () => {
    setError("");
    if (!password.trim()) return setError(friendlyError(new Error(t("auth.authError"))));
    setBusy(true);
    try {
      await api.post("/auth/confirm-password", { phone, password });
      onDone();
    } catch (e) {
      setError(friendlyError(e));
    }
    setBusy(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-xl dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">{t("accounts.connectTitle")}</h2>
          <IconButton label={t("common.cancel")} onClick={onClose}>
            <Icon name="close" className="h-4 w-4" />
          </IconButton>
        </div>

        <div className="mt-4 flex items-center gap-1 text-xs text-slate-400">
          {(["phone", "code", "password"] as FlowStep[]).map((s, i) => (
            <span key={s} className="flex items-center gap-1">
              {i > 0 && <span>→</span>}
              <span className={step === s ? "text-emerald-600" : ""}>{stepLabel(s, t)}</span>
            </span>
          ))}
        </div>

        {step === "phone" && (
          <div className="mt-4">
            <label className="text-sm text-slate-600 dark:text-slate-300">{t("accounts.phoneLabel")}</label>
            <input
              type="text"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder={t("accounts.phonePlaceholder")}
              className="mt-1 w-full sw-input"
              autoFocus
            />
          </div>
        )}

        {step === "phone" && busy && (
          <p className="mt-3 text-sm text-slate-500 dark:text-slate-400">{t("accounts.sendingCode")}</p>
        )}

        {step === "phone" && !busy && countdown > 0 && (
          <p className="mt-3 text-sm text-slate-500 dark:text-slate-400">
            {t("accounts.codeSentNotice", { seconds: countdown })}
          </p>
        )}

        {step === "code" && (
          <div className="mt-4">
            <label className="text-sm text-slate-600 dark:text-slate-300">
              {t("accounts.codeLabel")}
            </label>
            <input
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder={t("accounts.codePlaceholder")}
              className="mt-1 w-full sw-input"
              autoFocus
            />
          </div>
        )}

        {step === "password" && (
          <div className="mt-4">
            <label className="text-sm text-slate-600 dark:text-slate-300">
              {t("accounts.passwordLabel")}
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t("accounts.passwordPlaceholder")}
              className="mt-1 w-full sw-input"
              autoFocus
            />
          </div>
        )}

        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button>
          {step === "phone" && (
            <Button onClick={sendCode} disabled={busy || countdown > 0}>
              {busy
                ? "…"
                : countdown > 0
                  ? t("accounts.sendCodeCountdown", { seconds: countdown })
                  : t("common.sendCode")}
            </Button>
          )}
          {step === "code" && (
            <Button onClick={confirmCode} disabled={busy}>{busy ? "…" : t("common.confirm")}</Button>
          )}
          {step === "password" && (
            <Button onClick={confirmPassword} disabled={busy}>{busy ? "…" : t("common.login")}</Button>
          )}
        </div>
      </div>
    </div>
  );
}

function stepLabel(s: FlowStep, t: (key: string) => string): string {
  return s === "phone" ? t("common.phone") : s === "code" ? t("common.code") : t("common.twofa");
}