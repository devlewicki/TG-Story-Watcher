"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { api, type ActivityEvent } from "@/lib/api";
import { Button, Card, CardHeader, ErrorBanner, Spinner, Switch } from "@/components/ui";
import { timeAgo } from "@/lib/format";

const PlacesMap = dynamic(() => import("@/components/PlacesMap"), {
  ssr: false,
  loading: () => (
    <div className="flex h-[420px] items-center justify-center rounded-xl border border-slate-200 bg-slate-50 text-sm text-slate-400 dark:border-slate-800 dark:bg-slate-900">
      Загружаем карту…
    </div>
  ),
});

type DiscoveryConfig = {
  enabled: boolean;
  hashtags: string[];
  locations: string[];
  auto_add_places: boolean;
  search_interval: number;
  search_results_max: number;
};

type Place = {
  id: number;
  venue_id: string;
  title: string;
  address: string | null;
  provider: string;
  lat: number | null;
  long: number | null;
};

type GeoSuggestion = {
  name: string;
  display_name: string;
  lat: number;
  lon: number;
  type: string;
  category: string;
};

type Suggestion = {
  kind: "place" | "city";
  title: string;
  subtitle: string;
  venueId?: string;
  cityName?: string;
};

const venueIdOf = (line: string) =>
  line.startsWith("venue:") ? line.slice("venue:".length).trim() : null;

export default function DiscoveryPage() {
  const [cfg, setCfg] = useState<DiscoveryConfig | null>(null);
  const [places, setPlaces] = useState<Place[]>([]);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [saveState, setSaveState] = useState<"saved" | "saving" | "dirty">("saved");
  const [lastRun, setLastRun] = useState<ActivityEvent | null>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [geoQuery, setGeoQuery] = useState("");
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [showSugg, setShowSugg] = useState(false);
  const geoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [placeFilter, setPlaceFilter] = useState("");
  const [placesOpen, setPlacesOpen] = useState(false);
  const [selectedOpen, setSelectedOpen] = useState(false);
  const [mapOpen, setMapOpen] = useState(false);
  const [tagInput, setTagInput] = useState("");

  const loadPlaces = () =>
    api
      .get<Place[]>("/discovery/places")
      .then(setPlaces)
      .catch(() => {});

  const loadLastRun = async () => {
    try {
      const ev = await api.get<ActivityEvent[]>("/history/activity?limit=100");
      const disc = ev.filter((e) => (e.event_type || "").startsWith("discovery"));
      setLastRun(disc[0] || null);
    } catch {
      /* best-effort */
    }
  };

  useEffect(() => {
    api
      .get<DiscoveryConfig>("/discovery/config")
      .then(setCfg)
      .catch((e) => setError((e as Error).message));
    loadPlaces();
    loadLastRun();
  }, []);

  if (error && !cfg) return <ErrorBanner message={error} />;
  if (!cfg) return <Spinner />;

  // Auto-save with debounce: no separate "save" button needed.
  const update = (patch: Partial<DiscoveryConfig>) => {
    const next = { ...cfg, ...patch };
    setCfg(next);
    setSaveState("dirty");
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      setSaveState("saving");
      try {
        await api.post("/discovery/config", next);
        setSaveState("saved");
      } catch (e) {
        setError((e as Error).message);
        setSaveState("saved");
      }
    }, 600);
  };

  const search = async () => {
    setBusy(true);
    setError("");
    setNote("");
    try {
      const res = await api.post<{ note: string }>("/discovery/search");
      setNote(res.note || "Поиск запущен.");
      setTimeout(loadLastRun, 8000);
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  };

  const addTag = () => {
    const t = tagInput.trim().replace(/^#/, "").toLowerCase();
    if (t && !cfg.hashtags.includes(t)) {
      update({ hashtags: [...cfg.hashtags, t] });
    }
    setTagInput("");
  };

  const removeTag = (t: string) =>
    update({ hashtags: cfg.hashtags.filter((x) => x !== t) });

  const togglePlace = (p: Place) => {
    const line = `venue:${p.venue_id}`;
    const has = cfg.locations.includes(line);
    update({
      locations: has
        ? cfg.locations.filter((l) => l !== line)
        : [...cfg.locations, line],
    });
  };

  const onGeoInput = (v: string) => {
    setGeoQuery(v);
    if (geoTimer.current) clearTimeout(geoTimer.current);
    const q = v.trim();
    if (q.length < 2) {
      setSuggestions([]);
      setShowSugg(false);
      return;
    }
    geoTimer.current = setTimeout(async () => {
      try {
        const [placesRes, geocodeRes] = await Promise.all([
          api.get<Place[]>(`/discovery/places?q=${encodeURIComponent(q)}`),
          api.get<GeoSuggestion[]>(`/discovery/geocode?q=${encodeURIComponent(q)}`),
        ]);
        const sugg: Suggestion[] = [
          ...placesRes.slice(0, 5).map((p) => ({
            kind: "place" as const,
            title: p.title,
            subtitle: p.address || "место из собранных",
            venueId: p.venue_id,
          })),
          ...geocodeRes.slice(0, 5).map((g) => ({
            kind: "city" as const,
            title: g.name,
            subtitle: g.display_name.split(",").slice(0, 3).join(", "),
            cityName: g.name,
          })),
        ];
        setSuggestions(sugg);
        setShowSugg(true);
      } catch {
        /* autocomplete is best-effort */
      }
    }, 350);
  };

  const pickSuggestion = (s: Suggestion) => {
    const line = s.kind === "place" ? `venue:${s.venueId}` : `city:${s.cityName}`;
    if (line && !cfg.locations.includes(line)) {
      update({ locations: [...cfg.locations, line] });
    }
    setGeoQuery("");
    setSuggestions([]);
    setShowSugg(false);
  };

  const removeLocation = (line: string) =>
    update({ locations: cfg.locations.filter((l) => l !== line) });

  const deletePlace = async (p: Place) => {
    try {
      await api.delete(`/discovery/places/${p.id}`);
      setPlaces(places.filter((x) => x.id !== p.id));
      update({
        locations: cfg.locations.filter((l) => venueIdOf(l) !== p.venue_id),
      });
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const locationLabel = (line: string): { label: string; icon: string } => {
    const vid = venueIdOf(line);
    if (vid) {
      const p = places.find((x) => x.venue_id === vid);
      return p
        ? { label: p.title, icon: "📍" }
        : { label: `место (${vid.slice(0, 8)}…)`, icon: "📍" };
    }
    if (line.startsWith("city:")) return { label: line.slice(5), icon: "🏙" };
    return { label: line, icon: "📍" };
  };

  const filteredPlaces = places.filter((p) => {
    const f = placeFilter.trim().toLowerCase();
    if (!f) return true;
    return (
      p.title.toLowerCase().includes(f) ||
      (p.address || "").toLowerCase().includes(f) ||
      p.venue_id.toLowerCase().includes(f)
    );
  });

  const selectAll = () => {
    const newLines = filteredPlaces
      .filter((p) => !cfg.locations.includes(`venue:${p.venue_id}`))
      .map((p) => `venue:${p.venue_id}`);
    if (newLines.length > 0) update({ locations: [...cfg.locations, ...newLines] });
  };

  const deselectAll = () => {
    const vids = new Set(filteredPlaces.map((p) => p.venue_id));
    update({
      locations: cfg.locations.filter((l) => {
        const vid = venueIdOf(l);
        return !(vid && vids.has(vid));
      }),
    });
  };

  const selectedVids = new Set(
    cfg.locations.map((l) => venueIdOf(l)).filter((v): v is string => Boolean(v))
  );

  const intervalMin = Math.max(1, Math.round((cfg.search_interval || 60) / 60));
  const saveLabel =
    saveState === "saving"
      ? "Сохранение…"
      : saveState === "dirty"
      ? "Не сохранено"
      : "Сохранено";

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-xl font-semibold">Поиск историй</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Находим новые истории по хештегам и местам, собираем гео-метки
          </p>
          {lastRun && (
            <p className="mt-1 text-xs text-slate-400">
              Последний поиск: {timeAgo(lastRun.created_at)} · {lastRun.message}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <span
            className={`text-xs ${
              saveState === "dirty"
                ? "text-amber-500"
                : saveState === "saving"
                ? "text-slate-400"
                : "text-emerald-600 dark:text-emerald-400"
            }`}
          >
            {saveState === "dirty" ? "• " : saveState === "saved" ? "✓ " : ""}
            {saveLabel}
          </span>
          <Button onClick={search} disabled={busy}>
            {busy ? "Запускаем…" : "Поиск"}
          </Button>
        </div>
      </div>

      {error && <ErrorBanner message={error} />}
      {note && <p className="text-sm text-emerald-600 dark:text-emerald-400">{note}</p>}

      <Card>
        <CardHeader title="Автопоиск" subtitle="Как часто искать новые истории" />
        <div className="space-y-4 p-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-medium text-slate-700 dark:text-slate-200">
                Искать истории автоматически
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400">
                Поиск будет повторяться сам по расписанию
              </div>
            </div>
            <Switch checked={cfg.enabled} onChange={(v) => update({ enabled: v })} />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="text-sm font-medium text-slate-700 dark:text-slate-200">
                Проверять каждые
              </label>
              <div className="mt-1.5 flex items-center gap-2">
                <input
                  type="number"
                  min={1}
                  value={intervalMin}
                  onChange={(e) =>
                    update({ search_interval: Math.max(1, Number(e.target.value)) * 60 })
                  }
                  className="w-24 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
                />
                <span className="text-sm text-slate-500">минут</span>
              </div>
              <p className="mt-1 text-xs text-slate-400">
                Не чаще 1 раза в минуту — Telegram ограничивает частоту поиска
              </p>
            </div>
            <div>
              <label className="text-sm font-medium text-slate-700 dark:text-slate-200">
                Обрабатывать за один поиск
              </label>
              <div className="mt-1.5 flex items-center gap-2">
                <input
                  type="number"
                  min={1}
                  value={cfg.search_results_max}
                  onChange={(e) =>
                    update({ search_results_max: Math.max(1, Number(e.target.value)) })
                  }
                  className="w-24 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
                />
                <span className="text-sm text-slate-500">историй</span>
              </div>
            </div>
          </div>
        </div>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Хештеги"
            subtitle="Истории, отмеченные этими тегами"
          />
          <div className="space-y-3 p-5">
            <div className="flex flex-wrap gap-2">
              {cfg.hashtags.length === 0 && (
                <p className="text-sm text-slate-400">Хештеги пока не добавлены</p>
              )}
              {cfg.hashtags.map((t) => (
                <span
                  key={t}
                  className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1.5 text-sm text-slate-700 dark:bg-slate-800 dark:text-slate-200"
                >
                  #{t}
                  <button
                    onClick={() => removeTag(t)}
                    className="text-slate-400 transition-colors hover:text-red-500"
                    title="Убрать"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-3.5 w-3.5">
                      <path d="M6 6l12 12M18 6L6 18" />
                    </svg>
                  </button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addTag()}
                placeholder="Например: волхов"
                className="flex-1 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
              />
              <Button variant="secondary" onClick={addTag}>Добавить</Button>
            </div>
            <p className="text-xs text-slate-400">
              Подойдут названия городов, районов, увлечений: волхов, спб, путешествия
            </p>
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Места и города"
            subtitle="Где искать истории по геолокации"
          />
          <div className="space-y-4 p-5">
            {/* Auto-add toggle */}
            <div className="flex items-start justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50/60 p-3.5 dark:border-emerald-500/20 dark:bg-emerald-500/5">
              <div>
                <div className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  Автоматически добавлять собранные места в поиск
                </div>
                <div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                  Каждое найденное место само попадает в «Ищем сейчас» на
                  следующем цикле поиска — ничего не надо отмечать вручную
                </div>
              </div>
              <Switch
                checked={cfg.auto_add_places}
                onChange={(v) => update({ auto_add_places: v })}
              />
            </div>

            {/* Map */}
            <div>
              <button
                onClick={() => setMapOpen(!mapOpen)}
                className="flex w-full items-center justify-between rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 dark:border-slate-800 dark:text-slate-200 dark:hover:bg-slate-800/50"
              >
                <span className="flex items-center gap-2">
                  🗺
                  Собранные места на карте{" "}
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                    {places.length}
                  </span>
                </span>
                <span className="flex items-center gap-1 text-xs font-normal text-slate-400">
                  {mapOpen ? "Свернуть" : "Открыть"}
                  <svg
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className={`h-4 w-4 transition-transform ${mapOpen ? "rotate-180" : ""}`}
                  >
                    <path d="m6 9 6 6 6-6" />
                  </svg>
                </span>
              </button>
              {mapOpen && (
                <div className="mt-2">
                  <PlacesMap
                    places={places}
                    selectedVids={selectedVids}
                    onToggle={(p) =>
                      togglePlace({
                        id: p.id,
                        venue_id: p.venue_id,
                        title: p.title,
                        address: p.address ?? null,
                        provider: "four square",
                        lat: p.lat ?? null,
                        long: p.long ?? null,
                      } satisfies Place)
                    }
                  />
                </div>
              )}
            </div>

            {/* Selected locations — compact summary + expandable panel */}
            <div>
              <div className="mb-2 flex items-center justify-between">
                <div className="text-xs font-medium uppercase tracking-wide text-slate-400">
                  Ищем сейчас
                </div>
                {cfg.locations.length > 0 && (
                  <button
                    onClick={() => update({ locations: [] })}
                    className="text-xs font-medium text-slate-400 transition-colors hover:text-red-500"
                  >
                    Очистить все
                  </button>
                )}
              </div>
              {cfg.locations.length === 0 && !cfg.auto_add_places ? (
                <p className="text-sm text-slate-400">
                  Пока ничего не выбрано — добавьте место или город ниже
                </p>
              ) : cfg.auto_add_places && cfg.locations.length === 0 ? (
                <p className="text-sm text-emerald-600 dark:text-emerald-400">
                  Ищутся все собранные места ({places.length}) автоматически
                </p>
              ) : (
                <div className="rounded-xl border border-slate-200 dark:border-slate-800">
                  <button
                    onClick={() => setSelectedOpen(!selectedOpen)}
                    className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left hover:bg-slate-50 dark:hover:bg-slate-800/50"
                  >
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-sm dark:bg-emerald-500/10">
                      {selectedOpen ? "✕" : "📍"}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-slate-700 dark:text-slate-200">
                        {cfg.locations.length}{" "}
                        {cfg.locations.length === 1 ? "место" : cfg.locations.length < 5 ? "места" : "мест"}{" "}
                        в поиске
                      </span>
                      <span className="block truncate text-xs text-slate-400">
                        {cfg.locations
                          .slice(0, 3)
                          .map((l) => locationLabel(l).label)
                          .join(", ")}
                        {cfg.locations.length > 3 ? "…" : ""}
                      </span>
                    </span>
                    <svg
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      className={`h-4 w-4 shrink-0 text-slate-400 transition-transform ${selectedOpen ? "rotate-180" : ""}`}
                    >
                      <path d="m6 9 6 6 6-6" />
                    </svg>
                  </button>
                  {selectedOpen && (
                    <div className="max-h-56 space-y-0.5 overflow-auto border-t border-slate-200 p-2 dark:border-slate-800">
                      {cfg.locations.map((line) => {
                        const { label, icon } = locationLabel(line);
                        return (
                          <div
                            key={line}
                            className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-slate-100 dark:hover:bg-slate-800"
                          >
                            <span className="text-sm">{icon}</span>
                            <span className="min-w-0 flex-1 truncate text-sm">{label}</span>
                            <button
                              onClick={() => removeLocation(line)}
                              className="text-slate-300 transition-colors hover:text-red-500 dark:text-slate-600"
                              title="Убрать"
                            >
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-4 w-4">
                                <path d="M6 6l12 12M18 6L6 18" />
                              </svg>
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Autocomplete */}
            <div className="relative">
              <input
                value={geoQuery}
                onChange={(e) => onGeoInput(e.target.value)}
                onFocus={() => suggestions.length > 0 && setShowSugg(true)}
                onBlur={() => setTimeout(() => setShowSugg(false), 150)}
                placeholder="Добавить место или город…"
                className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
              />
              {showSugg && suggestions.length > 0 && (
                <div className="absolute z-10 mt-1 max-h-64 w-full overflow-auto rounded-xl border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-800">
                  {suggestions.map((s, i) => (
                    <button
                      key={`${s.kind}-${i}`}
                      onMouseDown={() => pickSuggestion(s)}
                      className="block w-full px-3 py-2 text-left hover:bg-slate-100 dark:hover:bg-slate-700"
                    >
                      <span className="text-sm font-medium">{s.title}</span>
                      <span
                        className={`ml-2 rounded px-1.5 py-0.5 text-[10px] uppercase ${
                          s.kind === "place"
                            ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400"
                            : "bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-400"
                        }`}
                      >
                        {s.kind === "place" ? "место" : "город"}
                      </span>
                      <div className="truncate text-xs text-slate-500 dark:text-slate-400">
                        {s.subtitle}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Collected places */}
            <div className="rounded-xl border border-slate-200 dark:border-slate-800">
              <div
                onClick={() => setPlacesOpen(!placesOpen)}
                className="flex cursor-pointer w-full items-center justify-between px-4 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800/50"
              >
                <span className="flex items-center gap-2">
                  Собранные места{" "}
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                    {places.length}
                  </span>
                </span>
                <span className="flex items-center gap-2">
                  <span className="hidden text-xs font-normal text-slate-400 sm:inline">
                    из историй автоматически
                  </span>
                  <svg
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className={`h-4 w-4 text-slate-400 transition-transform ${placesOpen ? "rotate-180" : ""}`}
                  >
                    <path d="m6 9 6 6 6-6" />
                  </svg>
                </span>
              </div>
              {placesOpen && (
                <div className="space-y-2 border-t border-slate-200 p-3 dark:border-slate-800">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex gap-3 text-xs">
                      <button onClick={selectAll} className="font-medium text-emerald-600 hover:underline dark:text-emerald-400">
                        Выделить все
                      </button>
                      <button onClick={deselectAll} className="font-medium text-slate-500 hover:underline dark:text-slate-400">
                        Снять все
                      </button>
                    </div>
                    <input
                      value={placeFilter}
                      onChange={(e) => setPlaceFilter(e.target.value)}
                      placeholder="Поиск места…"
                      className="w-40 rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-800"
                    />
                  </div>
                  {places.length === 0 ? (
                    <p className="px-2 py-3 text-center text-xs text-slate-400">
                      Места появятся автоматически, когда в найденных историях
                      встретятся гео-метки
                    </p>
                  ) : (
                    <div className="max-h-56 space-y-0.5 overflow-auto">
                      {filteredPlaces.map((p) => {
                        const checked = cfg.locations.includes(`venue:${p.venue_id}`);
                        return (
                          <label
                            key={p.id}
                            className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-slate-100 dark:hover:bg-slate-800"
                          >
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => togglePlace(p)}
                              className="h-4 w-4 accent-emerald-600"
                            />
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-sm">{p.title}</span>
                              {p.address && (
                                <span className="block truncate text-xs text-slate-400">
                                  {p.address}
                                </span>
                              )}
                            </span>
                            <button
                              onClick={(e) => {
                                e.preventDefault();
                                deletePlace(p);
                              }}
                              className="text-slate-300 transition-colors hover:text-red-500 dark:text-slate-600"
                              title="Удалить место"
                            >
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
                                <path d="M3 6h18M8 6V4h8v2m1 0-1 14H8L7 6" />
                              </svg>
                            </button>
                          </label>
                        );
                      })}
                      {filteredPlaces.length === 0 && (
                        <p className="px-2 py-3 text-center text-xs text-slate-400">
                          Ничего не найдено
                        </p>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>

            <p className="text-xs text-slate-400">
              {cfg.auto_add_places
                ? "Места собираются из найденных историй и ищутся автоматически. "
                : "Места собираются из найденных историй — отметьте чекбоксами нужные, и они добавятся в «Ищем сейчас»."}
            </p>
          </div>
        </Card>
      </div>
    </div>
  );
}
