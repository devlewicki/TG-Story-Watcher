"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { api, type ActivityEvent } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import { Button, Card, CardHeader, ErrorBanner, Icon, PageHeader, PageLoading, Switch } from "@/components/ui";
import type { IconName } from "@/components/ui";
import { timeAgo } from "@/lib/format";

function MapFallback() {
  const { t } = useTranslation();
  return (
    <div className="flex h-[420px] items-center justify-center rounded-xl border border-slate-200 bg-slate-50 text-sm text-slate-400 dark:border-slate-800 dark:bg-slate-900">
      {t("discovery.mapLoading")}
    </div>
  );
}

const PlacesMap = dynamic(() => import("@/components/PlacesMap"), {
  ssr: false,
  loading: () => <MapFallback />,
});

const GeoSearchMap = dynamic(() => import("@/components/GeoSearchMap"), {
  ssr: false,
  loading: () => <MapFallback />,
});

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

type DiscoveryConfig = {
  enabled: boolean;
  hashtags: string[];
  hashtags_enabled: boolean;
  locations: string[];
  auto_add_places: boolean;
  geo_search_enabled: boolean;
  geo_search_lat: number | null;
  geo_search_lng: number | null;
  geo_search_radius_km: number;
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

/* ------------------------------------------------------------------ */
/* Component                                                          */
/* ------------------------------------------------------------------ */

export default function DiscoveryPage() {
  const { t } = useTranslation();
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
  const [geoMapOpen, setGeoMapOpen] = useState(false);
  const [tagInput, setTagInput] = useState("");
  const [tagsExpanded, setTagsExpanded] = useState(false);
  const [geoVenueCount, setGeoVenueCount] = useState(0);

  /* ---- Load data ---- */

  const loadPlaces = () =>
    api.get<Place[]>("/discovery/places").then(setPlaces).catch(() => {});

  const loadLastRun = async () => {
    try {
      const ev = await api.get<ActivityEvent[]>("/history/activity?limit=100");
      const disc = ev.filter((e) => (e.event_type || "").startsWith("discovery"));
      setLastRun(disc[0] || null);
    } catch { /* best-effort */ }
  };

  useEffect(() => {
    api.get<DiscoveryConfig>("/discovery/config")
      .then(setCfg)
      .catch((e) => setError((e as Error).message));
    loadPlaces();
    loadLastRun();
  }, []);

  // Fetch geo venue count when geo config changes
  useEffect(() => {
    if (!cfg || !cfg.geo_search_enabled || cfg.geo_search_lat == null || cfg.geo_search_lng == null) {
      setGeoVenueCount(0);
      return;
    }
    let cancelled = false;
    api.post<{ count: number }>("/discovery/geo-radius",
      { lat: cfg.geo_search_lat, lng: cfg.geo_search_lng, radius_km: cfg.geo_search_radius_km })
      .then((res) => { if (!cancelled) setGeoVenueCount(res.count); })
      .catch(() => { if (!cancelled) setGeoVenueCount(0); });
    return () => { cancelled = true; };
  }, [cfg?.geo_search_enabled, cfg?.geo_search_lat, cfg?.geo_search_lng, cfg?.geo_search_radius_km]);

  if (error && !cfg) return <ErrorBanner message={error} />;
  if (!cfg) return <PageLoading />;

  /* ---- Config update helpers ---- */

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

  /* ---- Search trigger ---- */

  const search = async () => {
    setBusy(true);
    setError("");
    setNote("");
    try {
      const res = await api.post<{ note: string }>("/discovery/search");
      setNote(res.note || t("discovery.searchStarted"));
      setTimeout(loadLastRun, 8000);
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  };

  /* ---- Hashtag helpers ---- */

  const addTag = () => {
    const parts = tagInput.split(/[\s,;]+/).map((s) => s.trim().replace(/^#/, "").toLowerCase()).filter(Boolean);
    if (parts.length === 0) { setTagInput(""); return; }
    const existing = new Set(cfg.hashtags);
    const newTags = parts.filter((tg) => !existing.has(tg));
    if (newTags.length > 0) update({ hashtags: [...cfg.hashtags, ...newTags] });
    setTagInput("");
  };

  const removeTag = (tg: string) =>
    update({ hashtags: cfg.hashtags.filter((x) => x !== tg) });

  /* ---- Place helpers ---- */

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
    if (q.length < 2) { setSuggestions([]); setShowSugg(false); return; }
    geoTimer.current = setTimeout(async () => {
      try {
        const [placesRes, geocodeRes] = await Promise.all([
          api.get<Place[]>(`/discovery/places?q=${encodeURIComponent(q)}`),
          api.get<GeoSuggestion[]>(`/discovery/geocode?q=${encodeURIComponent(q)}`),
        ]);
        setSuggestions([
          ...placesRes.slice(0, 5).map((p) => ({
            kind: "place" as const, title: p.title,
            subtitle: p.address || t("discovery.placeFromCollection"), venueId: p.venue_id,
          })),
          ...geocodeRes.slice(0, 5).map((g) => ({
            kind: "city" as const, title: g.name,
            subtitle: g.display_name.split(",").slice(0, 3).join(", "), cityName: g.name,
          })),
        ]);
        setShowSugg(true);
      } catch { /* best-effort */ }
    }, 350);
  };

  const pickSuggestion = (s: Suggestion) => {
    const line = s.kind === "place" ? `venue:${s.venueId}` : `city:${s.cityName}`;
    if (line && !cfg.locations.includes(line))
      update({ locations: [...cfg.locations, line] });
    setGeoQuery(""); setSuggestions([]); setShowSugg(false);
  };

  const removeLocation = (line: string) =>
    update({ locations: cfg.locations.filter((l) => l !== line) });

  const deletePlace = async (p: Place) => {
    try {
      await api.delete(`/discovery/places/${p.id}`);
      setPlaces(places.filter((x) => x.id !== p.id));
      update({ locations: cfg.locations.filter((l) => venueIdOf(l) !== p.venue_id) });
    } catch (e) { setError((e as Error).message); }
  };

  const locationLabel = (line: string): { label: string; icon: IconName } => {
    const vid = venueIdOf(line);
    if (vid) {
      const p = places.find((x) => x.venue_id === vid);
      return p ? { label: p.title, icon: "mapPin" } : { label: `place (${vid.slice(0, 8)}…)`, icon: "mapPin" };
    }
    if (line.startsWith("city:")) return { label: line.slice(5), icon: "map" };
    return { label: line, icon: "mapPin" };
  };

  const filteredPlaces = places.filter((p) => {
    const f = placeFilter.trim().toLowerCase();
    if (!f) return true;
    return p.title.toLowerCase().includes(f) || (p.address || "").toLowerCase().includes(f) || p.venue_id.toLowerCase().includes(f);
  });

  const selectAll = () => {
    const newLines = filteredPlaces.filter((p) => !cfg.locations.includes(`venue:${p.venue_id}`)).map((p) => `venue:${p.venue_id}`);
    if (newLines.length > 0) update({ locations: [...cfg.locations, ...newLines] });
  };

  const deselectAll = () => {
    const vids = new Set(filteredPlaces.map((p) => p.venue_id));
    update({ locations: cfg.locations.filter((l) => { const vid = venueIdOf(l); return !(vid && vids.has(vid)); }) });
  };

  const selectedVids = new Set(
    cfg.locations.map((l) => venueIdOf(l)).filter((v): v is string => Boolean(v))
  );

  /* ---- Derived ---- */

  const saveLabel =
    saveState === "saving" ? t("common.saving") :
    saveState === "dirty" ? t("common.unsaved") :
    t("common.saved");

  return (
    <div className="space-y-5">
      {/* ---- Header + Search button ---- */}
      <PageHeader
        title={t("discovery.title")}
        subtitle={
          <>
            {t("discovery.subtitle")}
            {lastRun && (
              <span className="mt-1 block text-xs text-slate-400">
                {t("discovery.lastSearch")}: {timeAgo(lastRun.created_at)} · {lastRun.message}
              </span>
            )}
            {((cfg.hashtags_enabled && cfg.hashtags.length > 0) || (cfg.auto_add_places || cfg.locations.length > 0) || (cfg.geo_search_enabled && cfg.geo_search_lat != null)) && (
              <span className="mt-2 flex flex-wrap gap-1.5">
                {cfg.hashtags_enabled && cfg.hashtags.length > 0 && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 dark:bg-blue-500/10 dark:text-blue-400">
                    <Icon name="tag" className="h-3 w-3" />
                    {cfg.hashtags.length} {t("discovery.hashtags").toLowerCase()}
                  </span>
                )}
                {(cfg.auto_add_places || cfg.locations.length > 0) && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400">
                    <Icon name="mapPin" className="h-3 w-3" />
                    {cfg.locations.length || "auto"} {t("discovery.placesAndCities").toLowerCase()}
                  </span>
                )}
                {cfg.geo_search_enabled && cfg.geo_search_lat != null && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-400">
                    <Icon name="globe" className="h-3 w-3" />
                    {cfg.geo_search_radius_km} {t("discovery.kmShort")}
                  </span>
                )}
              </span>
            )}
          </>
        }
        right={
          <div className="flex shrink-0 items-center gap-3">
            <span
              className={`text-xs ${
                saveState === "dirty" ? "text-amber-500" :
                saveState === "saving" ? "text-slate-400" :
                "text-emerald-600 dark:text-emerald-400"
              }`}
            >
              {saveState === "dirty" ? "• " : saveState === "saved" ? "✓ " : ""}
              {saveLabel}
            </span>
            <Button onClick={search} disabled={busy}>
              <Icon name="search" className="h-4 w-4" />
              {busy ? t("discovery.searching") : t("discovery.search")}
            </Button>
          </div>
        }
      />

      {error && <ErrorBanner message={error} />}
      {note && <p className="text-sm text-emerald-600 dark:text-emerald-400">{note}</p>}

      {/* ---- Auto-search schedule ---- */}
      <Card>
        <CardHeader title={t("discovery.autoSearch")} subtitle={t("discovery.autoSearchDesc")} />
        <div className="space-y-4 p-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-medium text-slate-700 dark:text-slate-200">
                {t("discovery.autoSearchToggle")}
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400">
                {t("discovery.autoSearchToggleDesc")}
              </div>
            </div>
            <Switch checked={cfg.enabled} onChange={(v) => update({ enabled: v })} />
          </div>
        </div>
      </Card>

      {/* ---- 3 Search modes ---- */}
      <div className="grid gap-5 lg:grid-cols-3">

        {/* ======== 1. HASHTAGS ======== */}
        <Card>
          <CardHeader title={t("discovery.hashtags")} subtitle={t("discovery.hashtagsDesc")} />
          <div className="space-y-3 p-5">
            {/* Toggle */}
            <div className="flex items-start justify-between gap-3 rounded-xl border border-blue-200 bg-blue-50/60 p-3.5 dark:border-blue-500/20 dark:bg-blue-500/5">
              <div>
                <div className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {t("discovery.searchByHashtags")}
                </div>
                <div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                  {t("discovery.searchByHashtagsDesc")}
                </div>
              </div>
              <Switch checked={cfg.hashtags_enabled !== false} onChange={(v) => update({ hashtags_enabled: v })} />
            </div>
            {/* Tags list — collapsible */}
            {(() => {
              const ROW_HEIGHT = 36; const GAP = 8; const ROWS = 3;
              const collapsedMaxH = ROWS * (ROW_HEIGHT + GAP) - GAP;
              const overflows = cfg.hashtags.length > 30;
              return (
                <>
                  {cfg.hashtags.length > 0 && (
                    <div className="relative">
                      <div className="flex flex-wrap gap-2 overflow-hidden transition-all duration-300"
                        style={{ maxHeight: overflows && !tagsExpanded ? collapsedMaxH : undefined }}>
                        {cfg.hashtags.map((tg) => (
                          <span key={tg} className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1.5 text-sm text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                            #{tg}
                            <button onClick={() => removeTag(tg)} title={t("common.remove")}
                              className="text-slate-400 transition-colors hover:text-red-500">
                              <Icon name="close" className="h-3.5 w-3.5" />
                            </button>
                          </span>
                        ))}
                      </div>
                      {overflows && !tagsExpanded && (
                        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-white dark:from-slate-900" />
                      )}
                    </div>
                  )}
                  {cfg.hashtags.length === 0 && <p className="text-sm text-slate-400">{t("discovery.noHashtags")}</p>}
                  {overflows && (
                    <button onClick={() => setTagsExpanded(!tagsExpanded)}
                      className="text-xs font-medium text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300">
                      {tagsExpanded ? t("discovery.collapse") : t("discovery.showAllTags", { count: cfg.hashtags.length })}
                    </button>
                  )}
                </>
              );
            })()}
            <div className="flex gap-2">
              <input value={tagInput} onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addTag()}
                placeholder={t("discovery.tagPlaceholder")}
                className="flex-1 sw-input" />
              <Button variant="secondary" onClick={addTag}>{t("discovery.addTag")}</Button>
            </div>
            <p className="text-xs text-slate-400">{t("discovery.tagHint")}</p>
          </div>
        </Card>

        {/* ======== 2. PLACES & CITIES ======== */}
        <Card>
          <CardHeader title={t("discovery.placesAndCities")} subtitle={t("discovery.placesAndCitiesDesc")} />
          <div className="space-y-4 p-5">
            {/* Auto-add toggle */}
            <div className="flex items-start justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50/60 p-3.5 dark:border-emerald-500/20 dark:bg-emerald-500/5">
              <div>
                <div className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {t("discovery.autoAddPlaces")}
                </div>
                <div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                  {t("discovery.autoAddPlacesDesc")}
                </div>
              </div>
              <Switch checked={cfg.auto_add_places} onChange={(v) => update({ auto_add_places: v })} />
            </div>

            {/* Map toggle */}
            <div>
              <button onClick={() => setMapOpen(!mapOpen)}
                className="flex w-full items-center justify-between rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 dark:border-slate-800 dark:text-slate-200 dark:hover:bg-slate-800/50">
                <span className="flex items-center gap-2">
                  <Icon name="map" className="h-4 w-4 text-slate-400" />
                  {t("discovery.mapTitle")}
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">{places.length}</span>
                </span>
                <span className="flex items-center gap-1 text-xs font-normal text-slate-400">
                  {mapOpen ? t("discovery.collapse") : t("discovery.expand")}
                  <Icon name="chevron" className={`h-4 w-4 transition-transform ${mapOpen ? "rotate-180" : ""}`} />
                </span>
              </button>
              {mapOpen && (
                <div className="mt-2">
                  <PlacesMap places={places} selectedVids={selectedVids}
                    onToggle={(p) => togglePlace({
                      id: p.id, venue_id: p.venue_id, title: p.title,
                      address: p.address ?? null, provider: "four square",
                      lat: p.lat ?? null, long: p.long ?? null,
                    } satisfies Place)} />
                </div>
              )}
            </div>

            {/* Selected locations */}
            <div>
              <div className="mb-2 flex items-center justify-between">
                <div className="text-xs font-medium uppercase tracking-wide text-slate-400">
                  {t("discovery.searchingNow")}
                </div>
                {cfg.locations.length > 0 && (
                  <button onClick={() => update({ locations: [] })}
                    className="text-xs font-medium text-slate-400 transition-colors hover:text-red-500">
                    {t("discovery.clearAll")}
                  </button>
                )}
              </div>
              {cfg.locations.length === 0 && !cfg.auto_add_places ? (
                <p className="text-sm text-slate-400">{t("discovery.nothingSelected")}</p>
              ) : cfg.auto_add_places && cfg.locations.length === 0 ? (
                <p className="text-sm text-emerald-600 dark:text-emerald-400">
                  {t("discovery.autoSearchingAll", { count: places.length })}
                </p>
              ) : (
                <div className="rounded-xl border border-slate-200 dark:border-slate-800">
                  <button onClick={() => setSelectedOpen(!selectedOpen)}
                    className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left hover:bg-slate-50 dark:hover:bg-slate-800/50">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400">
                      {selectedOpen ? <Icon name="close" className="h-4 w-4" /> : <Icon name="mapPin" className="h-4 w-4" />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-slate-700 dark:text-slate-200">
                        {t("discovery.placesCount", { count: cfg.locations.length, one: cfg.locations.length, few: cfg.locations.length, many: cfg.locations.length })}
                      </span>
                      <span className="block truncate text-xs text-slate-400">
                        {cfg.locations.slice(0, 3).map((l) => locationLabel(l).label).join(", ")}
                        {cfg.locations.length > 3 ? "…" : ""}
                      </span>
                    </span>
                    <Icon name="chevron" className={`h-4 w-4 shrink-0 text-slate-400 transition-transform ${selectedOpen ? "rotate-180" : ""}`} />
                  </button>
                  {selectedOpen && (
                    <div className="max-h-56 space-y-0.5 overflow-auto border-t border-slate-200 p-2 dark:border-slate-800">
                      {cfg.locations.map((line) => {
                        const { label, icon } = locationLabel(line);
                        return (
                          <div key={line} className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-slate-100 dark:hover:bg-slate-800">
                            <Icon name={icon} className="h-4 w-4 shrink-0 text-slate-400" />
                            <span className="min-w-0 flex-1 truncate text-sm">{label}</span>
                            <button onClick={() => removeLocation(line)} title={t("common.remove")}
                              className="text-slate-300 transition-colors hover:text-red-500 dark:text-slate-600">
                              <Icon name="close" className="h-4 w-4" />
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
              <input value={geoQuery} onChange={(e) => onGeoInput(e.target.value)}
                onFocus={() => suggestions.length > 0 && setShowSugg(true)}
                onBlur={() => setTimeout(() => setShowSugg(false), 150)}
                placeholder={t("discovery.addPlaceOrCity")}
                className="w-full sw-input" />
              {showSugg && suggestions.length > 0 && (
                <div className="absolute z-10 mt-1 max-h-64 w-full overflow-auto rounded-xl border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-800">
                  {suggestions.map((s, i) => (
                    <button key={`${s.kind}-${i}`} onMouseDown={() => pickSuggestion(s)}
                      className="block w-full px-3 py-2 text-left hover:bg-slate-100 dark:hover:bg-slate-700">
                      <span className="text-sm font-medium">{s.title}</span>
                      <span className={`ml-2 rounded px-1.5 py-0.5 text-[10px] uppercase ${
                        s.kind === "place" ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400"
                          : "bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-400"
                      }`}>{s.kind === "place" ? t("discovery.place") : t("discovery.city")}</span>
                      <div className="truncate text-xs text-slate-500 dark:text-slate-400">{s.subtitle}</div>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Collected places */}
            <div className="rounded-xl border border-slate-200 dark:border-slate-800">
              <div onClick={() => setPlacesOpen(!placesOpen)}
                className="flex cursor-pointer w-full items-center justify-between px-4 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800/50">
                <span className="flex items-center gap-2">
                  {t("discovery.collectedPlaces")}
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">{places.length}</span>
                </span>
                <span className="flex items-center gap-2">
                  <span className="hidden text-xs font-normal text-slate-400 sm:inline">{t("discovery.fromStories")}</span>
                  <Icon name="chevron" className={`h-4 w-4 text-slate-400 transition-transform ${placesOpen ? "rotate-180" : ""}`} />
                </span>
              </div>
              {placesOpen && (
                <div className="space-y-2 border-t border-slate-200 p-3 dark:border-slate-800">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex gap-3 text-xs">
                      <button onClick={selectAll} className="font-medium text-emerald-600 hover:underline dark:text-emerald-400">{t("discovery.selectAll")}</button>
                      <button onClick={deselectAll} className="font-medium text-slate-500 hover:underline dark:text-slate-400">{t("discovery.deselectAll")}</button>
                    </div>
                    <input value={placeFilter} onChange={(e) => setPlaceFilter(e.target.value)}
                      placeholder={t("discovery.searchPlace")}
                      className="w-40 sw-input !py-1 text-xs" />
                  </div>
                  {places.length === 0 ? (
                    <p className="px-2 py-3 text-center text-xs text-slate-400">{t("discovery.emptyPlaces")}</p>
                  ) : (
                    <div className="max-h-56 space-y-0.5 overflow-auto">
                      {filteredPlaces.map((p) => {
                        const checked = cfg.locations.includes(`venue:${p.venue_id}`);
                        return (
                          <label key={p.id} className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-slate-100 dark:hover:bg-slate-800">
                            <input type="checkbox" checked={checked} onChange={() => togglePlace(p)} className="h-4 w-4 accent-emerald-600" />
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-sm">{p.title}</span>
                              {p.address && <span className="block truncate text-xs text-slate-400">{p.address}</span>}
                            </span>
                            <button onClick={(e) => { e.preventDefault(); deletePlace(p); }} title={t("common.delete")}
                              className="text-slate-300 transition-colors hover:text-red-500 dark:text-slate-600">
                              <Icon name="trash" className="h-4 w-4" />
                            </button>
                          </label>
                        );
                      })}
                      {filteredPlaces.length === 0 && <p className="px-2 py-3 text-center text-xs text-slate-400">{t("discovery.nothingFound")}</p>}
                    </div>
                  )}
                </div>
              )}
            </div>

            <p className="text-xs text-slate-400">
              {cfg.auto_add_places
                ? t("discovery.placesNoteAuto")
                : t("discovery.placesNoteManual")}
            </p>
          </div>
        </Card>

        {/* ======== 3. GEO-RADIUS ======== */}
        <Card>
          <CardHeader title={t("discovery.geoRadiusTitle")} subtitle={t("discovery.geoRadiusDesc")} />
          <div className="space-y-4 p-5">
            {/* Toggle */}
            <div className="flex items-start justify-between gap-3 rounded-xl border border-indigo-200 bg-indigo-50/60 p-3.5 dark:border-indigo-500/20 dark:bg-indigo-500/5">
              <div>
                <div className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {t("discovery.geoSearchToggle")}
                </div>
                <div className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                  {t("discovery.geoSearchToggleDesc")}
                </div>
              </div>
              <Switch checked={cfg.geo_search_enabled} onChange={(v) => update({ geo_search_enabled: v })} />
            </div>

            {/* Status summary */}
            {cfg.geo_search_enabled && cfg.geo_search_lat != null && cfg.geo_search_lng != null && (
              <div className="flex items-center gap-2 rounded-lg bg-indigo-50/50 px-3 py-2 text-xs text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-400">
                <Icon name="mapPin" className="h-3.5 w-3.5" />
                {cfg.geo_search_lat.toFixed(4)}, {cfg.geo_search_lng.toFixed(4)} · {cfg.geo_search_radius_km} {t("discovery.kmShort")}
              </div>
            )}

            {/* Map */}
            <div>
              <button onClick={() => setGeoMapOpen(!geoMapOpen)}
                className="flex w-full items-center justify-between rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 dark:border-slate-800 dark:text-slate-200 dark:hover:bg-slate-800/50">
                <span className="flex items-center gap-2">
                  <Icon name="globe" className="h-4 w-4 text-slate-400" />
                  {t("discovery.geoMapTitle")}
                </span>
                <span className="flex items-center gap-1 text-xs font-normal text-slate-400">
                  {geoMapOpen ? t("discovery.collapse") : t("discovery.expand")}
                  <Icon name="chevron" className={`h-4 w-4 transition-transform ${geoMapOpen ? "rotate-180" : ""}`} />
                </span>
              </button>
              {geoMapOpen && (
                <div className="mt-2">
                  <GeoSearchMap
                    geoEnabled={cfg.geo_search_enabled}
                    geoLat={cfg.geo_search_lat}
                    geoLng={cfg.geo_search_lng}
                    geoRadiusKm={cfg.geo_search_radius_km}
                    onConfigChange={(lat, lng, radiusKm) => update({
                      geo_search_lat: lat,
                      geo_search_lng: lng,
                      geo_search_radius_km: radiusKm,
                    })}
                    onSearchComplete={(res) => {
                      setNote(t("discovery.geoSearchDone", { count: res.venues_added }));
                      loadPlaces();
                      loadLastRun();
                    }}
                  />
                </div>
              )}
            </div>
          </div>
        </Card>
      </div>

      {/* ---- Summary row ---- */}
      <Card>
        <div className="p-5">
          <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
            {t("discovery.summaryTitle")}
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            {/* Hashtags summary */}
            <div className={`flex items-center gap-3 rounded-xl border px-4 py-3 transition-colors ${
              cfg.hashtags_enabled && cfg.hashtags.length > 0
                ? "border-blue-200 bg-blue-50/50 dark:border-blue-500/20 dark:bg-blue-500/5"
                : "border-slate-200 bg-slate-50/50 dark:border-slate-700 dark:bg-slate-800/30"
            }`}>
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
                cfg.hashtags_enabled && cfg.hashtags.length > 0
                  ? "bg-blue-100 text-blue-600 dark:bg-blue-500/20 dark:text-blue-400"
                  : "bg-slate-100 text-slate-400 dark:bg-slate-700 dark:text-slate-500"
              }`}>
                <Icon name="tag" className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {t("discovery.hashtags")}
                  </span>
                  <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${
                    cfg.hashtags_enabled && cfg.hashtags.length > 0
                      ? "bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-400"
                      : "bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-400"
                  }`}>
                    {cfg.hashtags_enabled
                      ? (cfg.hashtags.length > 0 ? t("discovery.onShort") : t("discovery.onEmpty"))
                      : t("discovery.offShort")}
                  </span>
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  {cfg.hashtags_enabled
                    ? t("discovery.tagsConfigured", { count: cfg.hashtags.length })
                    : t("discovery.disabled")}
                </div>
              </div>
            </div>

            {/* Places summary */}
            <div className={`flex items-center gap-3 rounded-xl border px-4 py-3 transition-colors ${
              (cfg.auto_add_places || cfg.locations.length > 0)
                ? "border-emerald-200 bg-emerald-50/50 dark:border-emerald-500/20 dark:bg-emerald-500/5"
                : "border-slate-200 bg-slate-50/50 dark:border-slate-700 dark:bg-slate-800/30"
            }`}>
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
                (cfg.auto_add_places || cfg.locations.length > 0)
                  ? "bg-emerald-100 text-emerald-600 dark:bg-emerald-500/20 dark:text-emerald-400"
                  : "bg-slate-100 text-slate-400 dark:bg-slate-700 dark:text-slate-500"
              }`}>
                <Icon name="mapPin" className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {t("discovery.placesAndCities")}
                  </span>
                  <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${
                    (cfg.auto_add_places || cfg.locations.length > 0)
                      ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-400"
                      : "bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-400"
                  }`}>
                    {(cfg.auto_add_places || cfg.locations.length > 0) ? t("discovery.onShort") : t("discovery.offShort")}
                  </span>
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  {cfg.auto_add_places && cfg.locations.length === 0
                    ? t("discovery.placesCollectedAuto", { collected: places.length })
                    : cfg.locations.length > 0
                    ? t("discovery.placesSelectedOf", { selected: cfg.locations.length, collected: places.length })
                    : t("discovery.disabled")}
                </div>
              </div>
            </div>

            {/* Geo-radius summary */}
            <div className={`flex items-center gap-3 rounded-xl border px-4 py-3 transition-colors ${
              cfg.geo_search_enabled && cfg.geo_search_lat != null
                ? "border-indigo-200 bg-indigo-50/50 dark:border-indigo-500/20 dark:bg-indigo-500/5"
                : "border-slate-200 bg-slate-50/50 dark:border-slate-700 dark:bg-slate-800/30"
            }`}>
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
                cfg.geo_search_enabled && cfg.geo_search_lat != null
                  ? "bg-indigo-100 text-indigo-600 dark:bg-indigo-500/20 dark:text-indigo-400"
                  : "bg-slate-100 text-slate-400 dark:bg-slate-700 dark:text-slate-500"
              }`}>
                <Icon name="globe" className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {t("discovery.geoRadiusTitle")}
                  </span>
                  <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${
                    cfg.geo_search_enabled && cfg.geo_search_lat != null
                      ? "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-400"
                      : "bg-slate-100 text-slate-500 dark:bg-slate-700 dark:text-slate-400"
                  }`}>
                    {cfg.geo_search_enabled && cfg.geo_search_lat != null ? t("discovery.onShort") : t("discovery.offShort")}
                  </span>
                </div>
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  {cfg.geo_search_enabled && cfg.geo_search_lat != null
                    ? t("discovery.geoSummary", { km: cfg.geo_search_radius_km, count: geoVenueCount })
                    : t("discovery.disabled")}
                </div>
              </div>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}
