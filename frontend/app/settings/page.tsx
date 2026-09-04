"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import { Card, CardHeader, ErrorBanner, Spinner, Switch } from "@/components/ui";

type SettingsMap = Record<string, Record<string, unknown>>;

type FieldType = "bool" | "number" | "text" | "select" | "readonly";

type FieldDef = {
  label: string;
  description?: string;
  type: FieldType;
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
  options?: { value: string; label: string }[];
  sensitive?: boolean;
  command?: { label: string; detect: () => string };
  slider?: { min: number; max: number; step?: number };
  emoji?: string[];
};

type SectionDef = {
  title: string;
  description: string;
  icon: string;
  fields: Record<string, FieldDef>;
};

// The discovery section is managed on its own page (Story Search).
// Queue is fully automatic — no user controls needed.
const HIDDEN_SECTIONS = new Set(["discovery", "queue"]);

function useSections(): Record<string, SectionDef> {
  const { t } = useTranslation();
  return {
    general: {
      title: t("settings.sections.general.title"),
      description: t("settings.sections.general.description"),
      icon: "⚙️",
      fields: {
        language: {
          label: t("settings.sections.general.fields.language.label"),
          type: "select",
          options: [
            { value: "ru", label: "Русский" },
            { value: "en", label: "English" },
          ],
        },
        timezone: {
          label: t("settings.sections.general.fields.timezone.label"),
          description: t("settings.sections.general.fields.timezone.description"),
          type: "text",
          command: {
            label: t("settings.sections.general.fields.timezone.autoDetect"),
            detect: () =>
              Intl.DateTimeFormat().resolvedOptions().timeZone ?? "",
          },
        },
        theme: {
          label: t("settings.sections.general.fields.theme.label"),
          type: "select",
          options: [
            { value: "dark", label: t("settings.sections.general.fields.theme.dark") },
            { value: "light", label: t("settings.sections.general.fields.theme.light") },
          ],
        },
        autostart: {
          label: t("settings.sections.general.fields.autostart.label"),
          description: t("settings.sections.general.fields.autostart.description"),
          type: "bool",
        },
      },
    },
    telegram: {
      title: t("settings.sections.telegram.title"),
      description: t("settings.sections.telegram.description"),
      icon: "✈️",
      fields: {
        api_id: { label: t("settings.sections.telegram.fields.apiId.label"), type: "text", sensitive: true },
        api_hash: { label: t("settings.sections.telegram.fields.apiHash.label"), type: "text", sensitive: true },
        reconnect: {
          label: t("settings.sections.telegram.fields.reconnect.label"),
          description: t("settings.sections.telegram.fields.reconnect.description"),
          type: "bool",
        },
      },
    },
    monitoring: {
      title: t("settings.sections.monitoring.title"),
      description: t("settings.sections.monitoring.description"),
      icon: "📡",
      fields: {
        realtime: {
          label: t("settings.sections.monitoring.fields.realtime.label"),
          description: t("settings.sections.monitoring.fields.realtime.description"),
          type: "bool",
        },
        resync: {
          label: t("settings.sections.monitoring.fields.resync.label"),
          description: t("settings.sections.monitoring.fields.resync.description"),
          type: "bool",
        },
      },
    },
    queue: {
      title: t("settings.sections.queue.title"),
      description: t("settings.sections.queue.description"),
      icon: "🗂",
      fields: {
        max_tasks: { label: t("settings.sections.queue.fields.maxTasks.label"), type: "number", min: 1, slider: { min: 50, max: 2000, step: 50 } },
        parallel: { label: t("settings.sections.queue.fields.parallel.label"), type: "number", min: 1, unit: t("settings.sections.queue.fields.parallel.unit"), slider: { min: 1, max: 10 } },
        backoff_factor: {
          label: t("settings.sections.queue.fields.backoffFactor.label"),
          description: t("settings.sections.queue.fields.backoffFactor.description"),
          type: "number",
          step: 0.5,
          slider: { min: 1, max: 5, step: 0.5 },
        },
        processing_timeout: {
          label: t("settings.sections.queue.fields.processingTimeout.label"),
          description: t("settings.sections.queue.fields.processingTimeout.description"),
          type: "number",
          min: 30,
          unit: t("settings.sections.queue.fields.processingTimeout.unit"),
          slider: { min: 60, max: 600, step: 30 },
        },
        max_auto_retries: {
          label: t("settings.sections.queue.fields.maxAutoRetries.label"),
          description: t("settings.sections.queue.fields.maxAutoRetries.description"),
          type: "number",
          min: 1,
        },
      },
    },
    limits: {
      title: t("settings.sections.limits.title"),
      description: t("settings.sections.limits.description"),
      icon: "🛡",
      fields: {
        views_per_minute: { label: t("settings.sections.limits.fields.viewsPerMinute.label"), type: "readonly" },
        views_per_hour: { label: t("settings.sections.limits.fields.viewsPerHour.label"), type: "readonly" },
        views_per_day: { label: t("settings.sections.limits.fields.viewsPerDay.label"), type: "number", min: 0, slider: { min: 50, max: 12000, step: 50 } },
      },
    },
    view: {
      title: t("settings.sections.view.title"),
      description: t("settings.sections.view.description"),
      icon: "❤️",
      fields: {
        auto_like: {
          label: t("settings.sections.view.fields.autoLike.label"),
          description: t("settings.sections.view.fields.autoLike.description"),
          type: "bool",
        },
        like_emoji: {
          label: t("settings.sections.view.fields.likeEmoji.label"),
          type: "text",
          emoji: ["👍", "❤️", "🔥", "😍", "😂", "😮", "😢", "👏", "💯", "🎉"],
        },
      },
    },
    filters: {
      title: t("settings.sections.filters.title"),
      description: t("settings.sections.filters.description"),
      icon: "🎯",
      fields: {
        include_contacts: { label: t("settings.sections.filters.fields.includeContacts.label"), type: "bool" },
        include_unknown: { label: t("settings.sections.filters.fields.includeUnknown.label"), type: "bool" },
        include_mutual_contacts: { label: t("settings.sections.filters.fields.includeMutualContacts.label"), type: "bool" },
        include_non_mutual: { label: t("settings.sections.filters.fields.includeNonMutual.label"), type: "bool" },
        include_channels: { label: t("settings.sections.filters.fields.includeChannels.label"), type: "bool" },
        include_groups: { label: t("settings.sections.filters.fields.includeGroups.label"), type: "bool" },
        include_bots: { label: t("settings.sections.filters.fields.includeBots.label"), type: "bool" },
        include_deleted: { label: t("settings.sections.filters.fields.includeDeleted.label"), type: "bool" },
        include_blocked: { label: t("settings.sections.filters.fields.includeBlocked.label"), type: "bool" },
      },
    },
  };
}

const inputCls =
  "mt-1.5 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 transition-colors focus:border-emerald-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100";

export default function SettingsPage() {
  const { t } = useTranslation();
  const SECTIONS = useSections();
  const [all, setAll] = useState<SettingsMap | null>(null);
  const [error, setError] = useState("");
  const [saveState, setSaveState] = useState<"saved" | "saving" | "dirty">(
    "saved"
  );
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    api
      .get<SettingsMap>("/settings")
      .then((d) => {
        // Backend now auto-derives all values from daily, just use them
        setAll(d);
        setSaveState("saved");
      })
      .catch((e) => setError((e as Error).message));
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, []);

  if (error && !all) return <ErrorBanner message={error} />;
  if (!all) return <Spinner />;

  const setField = (section: string, key: string, value: unknown) => {
    const next = {
      ...all,
      [section]: { ...all[section], [key]: value },
    };

    // Auto-calculate all derived parameters from daily limit
    if (section === "limits" && key === "views_per_day") {
      const daily = Math.max(50, Math.min(12000, Number(value) || 0));
      if (daily > 0) {
        const viewsPerHour = Math.floor(daily / 24);
        const viewsPerMinute = Math.ceil(daily / 1440);
        const avgDelay = 86400 / daily;
        const minDelay = Math.max(3, Math.min(20, Math.round(avgDelay * 0.3)));
        const maxDelay = Math.max(10, Math.min(120, Math.round(avgDelay * 1.5)));
        const parallel = daily >= 8000 ? 3 : daily >= 3000 ? 2 : 1;
        const checkInterval = Math.max(15, Math.min(60, 120 - Math.floor(daily / 100)));
        const searchesPerHour = Math.max(1, Math.min(10, Math.floor(daily / 1500)));
        const searchDelay = Math.max(60, Math.min(600, 900 - Math.floor(daily / 20)));

        next.limits = {
          ...next.limits,
          views_per_day: daily,
          views_per_hour: viewsPerHour,
          views_per_minute: viewsPerMinute,
          searches_per_hour: searchesPerHour,
          search_results_max: 50,
          search_delay: searchDelay,
        };
        next.view = { ...next.view, min_delay: minDelay, max_delay: maxDelay };
        next.queue = {
          ...next.queue,
          max_tasks: 50,
          parallel,
          backoff_factor: 2.0,
          processing_timeout: 300,
          max_auto_retries: 3,
        };
        next.monitoring = { ...next.monitoring, check_interval: checkInterval };
      }
    }

    setAll(next);
    // If language changed, update localStorage and notify I18nProvider
    if (section === "general" && key === "language" && (value === "ru" || value === "en")) {
      localStorage.setItem("storywatcher_lang", value);
      window.dispatchEvent(new Event("storywatcher:lang-changed"));
    }
    setSaveState("dirty");
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      setSaveState("saving");
      try {
        await api.put("/settings", next);
        setSaveState("saved");
        setError("");
      } catch (e) {
        setError((e as Error).message);
        setSaveState("saved");
      }
    }, 600);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">{t("settings.title")}</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t("settings.subtitle")}
          </p>
        </div>
      </div>

      {error && <ErrorBanner message={error} />}

      <div className="grid gap-4 lg:grid-cols-2">
        {Object.entries(SECTIONS).filter(([k]) => !HIDDEN_SECTIONS.has(k)).map(([sectionKey, section]) => (
          <Card key={sectionKey}>
            <CardHeader
              title={
                <span className="flex items-center gap-2">
                  <span className="text-base">{section.icon}</span>
                  {section.title}
                </span>
              }
              subtitle={section.description}
            />
            <div className="space-y-4 p-5">
        {Object.entries(section.fields).map(([key, def]) => {
          const value = all[sectionKey]?.[key];
          return (
            <FieldRow
              key={key}
              def={def}
              value={value}
              onChange={(v) => setField(sectionKey, key, v)}
            />
          );
        })}
            </div>
          </Card>
        ))}
      </div>

      <p className="text-xs text-slate-400 dark:text-slate-500">
        {t("settings.searchHint")}{" "}
        <span className="font-medium">{t("settings.searchHintBold")}</span>.
      </p>

      {/* Auto-save status bar */}
      <div className="sticky bottom-4 z-10 flex items-center gap-2 rounded-2xl border border-slate-200 bg-white/90 px-5 py-3 shadow-lg shadow-slate-200/60 backdrop-blur dark:border-slate-700 dark:bg-slate-900/90 dark:shadow-black/30">
        {saveState === "saving" ? (
          <span className="flex items-center gap-2 text-sm text-slate-400">
            <Spinner />
            {t("common.saving")}
          </span>
        ) : saveState === "dirty" ? (
          <span className="flex items-center gap-1.5 text-sm text-amber-500">
            <span className="h-2 w-2 rounded-full bg-amber-500" />
            {t("common.saving")}
          </span>
        ) : (
          <span className="flex items-center gap-1.5 text-sm text-emerald-600 dark:text-emerald-400">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
              <path d="m4 12 5 5L20 7" />
            </svg>
            {t("common.autoSaving")}
          </span>
        )}
      </div>
    </div>
  );
}

function FieldRow({
  def,
  value,
  onChange,
}: {
  def: FieldDef;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  // Read-only field: shows only label and computed value, no slider or input
  if (def.type === "readonly") {
    return (
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-slate-700 dark:text-slate-200">
            {def.label}
          </div>
        </div>
        <span className="rounded-lg bg-slate-100 px-3 py-1.5 text-sm font-semibold tabular-nums text-slate-600 dark:bg-slate-700 dark:text-slate-300">
          {String(value ?? 0)}
        </span>
      </div>
    );
  }

  if (def.type === "bool") {
    return (
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-slate-700 dark:text-slate-200">
            {def.label}
          </div>
          {def.description && (
            <div className="text-xs text-slate-500 dark:text-slate-400">{def.description}</div>
          )}
        </div>
        <Switch checked={Boolean(value)} onChange={onChange} />
      </div>
    );
  }

  return (
    <div>
      <label className="flex items-center gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-200">
        {def.label}
        {def.unit && (
          <span className="text-xs font-normal text-slate-400">{def.unit}</span>
        )}
      </label>
      {def.description && (
        <div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{def.description}</div>
      )}
      {def.type === "select" ? (
        <select
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          className={inputCls}
        >
          {(def.options || []).map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      ) : def.type === "number" && def.slider ? (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">{def.slider.min}{def.unit ? ` ${def.unit}` : ""}</span>
            <span className="rounded-lg bg-emerald-50 px-2.5 py-1 text-sm font-semibold tabular-nums text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400">
              {String(value ?? def.slider.min)} {def.unit || ""}
            </span>
            <span className="text-xs text-slate-400">{def.slider.max}{def.unit ? ` ${def.unit}` : ""}</span>
          </div>
          <input
            type="range"
            min={def.slider.min}
            max={def.slider.max}
            step={def.slider.step || 1}
            value={Number(value ?? def.slider.min)}
            onChange={(e) => onChange(Number(e.target.value))}
            className="h-2 w-full cursor-pointer appearance-none rounded-full bg-slate-200 accent-emerald-600 dark:bg-slate-700"
          />
        </div>
      ) : def.type === "number" ? (
        <div className="flex gap-2">
          <input
            type="number"
            value={value === null || value === undefined ? "" : String(value)}
            min={def.min}
            max={def.max}
            step={def.step}
            onChange={(e) =>
              onChange(e.target.value === "" ? "" : Number(e.target.value))
            }
            className={inputCls}
          />
          {def.command && (
            <button
              type="button"
              onClick={() => onChange(def.command?.detect())}
              className="shrink-0 rounded-xl border border-slate-300 px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:border-emerald-500 hover:text-emerald-600 dark:border-slate-700 dark:text-slate-300 dark:hover:border-emerald-500 dark:hover:text-emerald-400"
            >
              {def.command.label}
            </button>
          )}
        </div>
      ) : def.emoji ? (
        <div className="mt-1.5 flex flex-wrap gap-2">
          {def.emoji.map((em) => (
              <button
                key={em}
                type="button"
                onClick={() => onChange(em)}
                className={`flex h-10 w-10 items-center justify-center rounded-xl text-xl transition-all ${
                  value === em
                    ? "scale-110 bg-emerald-100 shadow-sm ring-2 ring-emerald-500 dark:bg-emerald-500/20 dark:ring-emerald-400"
                    : "bg-slate-100 opacity-50 hover:opacity-80 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700"
                }`}
              >
                {em}
              </button>
            ))}
        </div>
      ) : (
        <div className="flex gap-2">
          <input
            type={def.sensitive ? "password" : "text"}
            value={String(value ?? "")}
            onChange={(e) => onChange(e.target.value)}
            className={inputCls}
          />
          {def.command && (
            <button
              type="button"
              onClick={() => onChange(def.command?.detect())}
              className="shrink-0 rounded-xl border border-slate-300 px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:border-emerald-500 hover:text-emerald-600 dark:border-slate-700 dark:text-slate-300 dark:hover:border-emerald-500 dark:hover:text-emerald-400"
            >
              {def.command.label}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
