"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Card, CardHeader, ErrorBanner, Spinner, Switch } from "@/components/ui";

type SettingsMap = Record<string, Record<string, unknown>>;

type FieldType = "bool" | "number" | "text" | "select";

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
};

type SectionDef = {
  title: string;
  description: string;
  icon: string;
  fields: Record<string, FieldDef>;
};

const SECTIONS: Record<string, SectionDef> = {
  general: {
    title: "Общие",
    description: "Язык интерфейса, тема и поведение при запуске",
    icon: "⚙️",
    fields: {
      language: {
        label: "Язык",
        type: "select",
        options: [
          { value: "ru", label: "Русский" },
          { value: "en", label: "English" },
        ],
      },
      timezone: {
        label: "Часовой пояс",
        description: "Например: Europe/Moscow, UTC",
        type: "text",
        command: {
          label: "Автоопределить",
          detect: () =>
            Intl.DateTimeFormat().resolvedOptions().timeZone ?? "",
        },
      },
      theme: {
        label: "Тема",
        type: "select",
        options: [
          { value: "dark", label: "Тёмная" },
          { value: "light", label: "Светлая" },
        ],
      },
      autostart: {
        label: "Автозапуск",
        description: "Запускать автоматизацию при старте приложения",
        type: "bool",
      },
    },
  },
  telegram: {
    title: "Telegram",
    description: "API-доступ и поведение соединения",
    icon: "✈️",
    fields: {
      api_id: { label: "API ID", type: "text", sensitive: true },
      api_hash: { label: "API Hash", type: "text", sensitive: true },
      reconnect: {
        label: "Переподключение",
        description: "Автоматически переподключаться при обрыве соединения",
        type: "bool",
      },
    },
  },
  monitoring: {
    title: "Мониторинг",
    description: "Как часто опрашивается Telegram и синхронизируются истории",
    icon: "📡",
    fields: {
      check_interval: { label: "Интервал проверки", type: "number", unit: "сек" },
      realtime: {
        label: "Обновления в реальном времени",
        description: "Обрабатывать обновления по мере поступления",
        type: "bool",
      },
      resync: {
        label: "Резервная синхронизация",
        description: "Восстанавливать пропущенные истории после перезапуска",
        type: "bool",
      },
    },
  },
  queue: {
    title: "Очередь",
    description: "Обработка очереди просмотра",
    icon: "🗂",
    fields: {
      max_tasks: { label: "Максимум задач за цикл", type: "number", min: 1 },
      parallel: { label: "Параллельная обработка", type: "number", min: 1, unit: "задач" },
      backoff_factor: {
        label: "Множитель повтора",
        description: "Экспоненциальная задержка между повторами ошибок",
        type: "number",
        step: 0.5,
      },
      processing_timeout: {
        label: "Таймаут обработки",
        description: "Задача в PROCESSING дольше этого времени считается зависшей (после падения воркера) и ставится обратно в очередь",
        type: "number",
        min: 30,
        unit: "сек",
      },
      max_auto_retries: {
        label: "Авто-повторы",
        description: "Сколько раз автоматически возвращать зависшую задачу; дальше — только вручную",
        type: "number",
        min: 1,
      },
    },
  },
  limits: {
    title: "Лимиты",
    description: "Ограничения на просмотры и поиск — защита от блокировки",
    icon: "🛡",
    fields: {
      views_per_minute: { label: "Просмотров в минуту", type: "number", min: 0 },
      views_per_hour: { label: "Просмотров в час", type: "number", min: 0 },
      views_per_day: { label: "Просмотров в сутки", type: "number", min: 0 },
      searches_per_hour: { label: "Поисков в час", type: "number", min: 0 },
      search_results_max: { label: "Макс. результатов поиска", type: "number", min: 1 },
      search_delay: { label: "Задержка между поисками", type: "number", min: 1, unit: "сек" },
    },
  },
  view: {
    title: "Просмотр и реакции",
    description: "Задержки перед просмотром и автолайк",
    icon: "❤️",
    fields: {
      min_delay: { label: "Минимальная задержка", type: "number", min: 0, unit: "сек" },
      max_delay: { label: "Максимальная задержка", type: "number", min: 0, unit: "сек" },
      auto_like: {
        label: "Автолайк",
        description: "Ставить реакцию на каждую просмотренную историю",
        type: "bool",
      },
      like_emoji: {
        label: "Эмодзи лайка",
        description: "Например: 👍 ❤️ 🔥",
        type: "text",
      },
    },
  },
  filters: {
    title: "Фильтры",
    description: "Каких авторов обрабатывать автоматически",
    icon: "🎯",
    fields: {
      include_contacts: { label: "Контакты", type: "bool" },
      include_unknown: { label: "Незнакомые пользователи", type: "bool" },
      include_mutual_contacts: { label: "Взаимные контакты", type: "bool" },
      include_non_mutual: { label: "Невзаимные контакты", type: "bool" },
      include_channels: { label: "Каналы", type: "bool" },
      include_groups: { label: "Группы", type: "bool" },
      include_bots: { label: "Боты", type: "bool" },
      include_deleted: { label: "Удалённые аккаунты", type: "bool" },
      include_blocked: { label: "Заблокированные", type: "bool" },
    },
  },
};

// The discovery section is managed on its own page (Поиск историй).
const HIDDEN_SECTIONS = new Set(["discovery"]);

const inputCls =
  "mt-1.5 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 transition-colors focus:border-emerald-500 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100";

export default function SettingsPage() {
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

  // Auto-save every change with a short debounce — no "Save all" button.
  const setField = (section: string, key: string, value: unknown) => {
    const next = {
      ...all,
      [section]: { ...all[section], [key]: value },
    };
    setAll(next);
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
          <h1 className="text-xl font-semibold">Настройки</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Настройки приложения и автоматизации
          </p>
        </div>
      </div>

      {error && <ErrorBanner message={error} />}

      <div className="grid gap-4 lg:grid-cols-2">
        {Object.entries(SECTIONS).map(([sectionKey, section]) => (
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
        Настройки поиска историй (хештеги, геолокации, интервал) — на странице{" "}
        <span className="font-medium">Поиск историй</span>.
      </p>

      {/* Auto-save status bar */}
      <div className="sticky bottom-4 z-10 flex items-center gap-2 rounded-2xl border border-slate-200 bg-white/90 px-5 py-3 shadow-lg shadow-slate-200/60 backdrop-blur dark:border-slate-700 dark:bg-slate-900/90 dark:shadow-black/30">
        {saveState === "saving" ? (
          <span className="flex items-center gap-2 text-sm text-slate-400">
            <Spinner />
            Сохранение…
          </span>
        ) : saveState === "dirty" ? (
          <span className="flex items-center gap-1.5 text-sm text-amber-500">
            <span className="h-2 w-2 rounded-full bg-amber-500" />
            Сохраняем…
          </span>
        ) : (
          <span className="flex items-center gap-1.5 text-sm text-emerald-600 dark:text-emerald-400">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
              <path d="m4 12 5 5L20 7" />
            </svg>
            Изменения сохраняются автоматически
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
