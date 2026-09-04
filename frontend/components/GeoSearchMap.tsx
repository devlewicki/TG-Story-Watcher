"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  MapContainer, TileLayer, Marker, Circle, Popup, useMap, useMapEvents,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { api } from "@/lib/api";

/* ------------------------------------------------------------------ */
/* Types                                                              */
/* ------------------------------------------------------------------ */

type GeoSuggestion = { name: string; display_name: string; lat: number; lon: number };

type VenueResult = {
  id: number; venue_id: string; title: string; address: string | null;
  lat: number; long: number; distance_km: number;
};

type GeoSearchResult = { places: VenueResult[]; count: number };

type GeoSearchResponse = {
  ok: boolean; status: string; venues_found: number; venues_added: number; total_locations: number;
};

/* ------------------------------------------------------------------ */
/* Icons                                                              */
/* ------------------------------------------------------------------ */

const pinIcon = L.divIcon({
  className: "",
  html: `<div style="width:28px;height:34px;display:flex;align-items:flex-start;justify-content:center">
    <svg viewBox="0 0 24 36" width="28" height="34" fill="none">
      <path d="M12 0C5.4 0 0 5.4 0 12c0 9 12 24 12 24s12-15 12-24C24 5.4 18.6 0 12 0z" fill="#10b981"/>
      <circle cx="12" cy="12" r="5" fill="white"/>
    </svg>
  </div>`,
  iconSize: [28, 34], iconAnchor: [14, 34], popupAnchor: [0, -30],
});

const myLocationIcon = L.divIcon({
  className: "",
  html: `<div style="width:20px;height:20px;border-radius:50%;border:3px solid #3b82f6;background:rgba(59,130,246,0.25);box-shadow:0 0 0 2px rgba(59,130,246,0.3)"></div>`,
  iconSize: [20, 20], iconAnchor: [10, 10],
});

const venueIcon = L.divIcon({
  className: "",
  html: `<div style="width:16px;height:16px;border-radius:50%;background:#f59e0b;border:2px solid white;box-shadow:0 1px 3px rgba(0,0,0,0.3)"></div>`,
  iconSize: [16, 16], iconAnchor: [8, 8], popupAnchor: [0, -10],
});

/* ------------------------------------------------------------------ */
/* Map helpers                                                        */
/* ------------------------------------------------------------------ */

function MapClickHandler({ onMapClick }: { onMapClick: (lat: number, lng: number) => void }) {
  useMapEvents({ click(e) { onMapClick(e.latlng.lat, e.latlng.lng); } });
  return null;
}

function FlyTo({ center, zoom }: { center: [number, number]; zoom: number }) {
  const map = useMap();
  useEffect(() => { map.flyTo(center, zoom, { duration: 1.2 }); }, [center, zoom, map]);
  return null;
}

/* ------------------------------------------------------------------ */
/* Component                                                          */
/* ------------------------------------------------------------------ */

export default function GeoSearchMap({
  geoEnabled,
  geoLat,
  geoLng,
  geoRadiusKm,
  onConfigChange,
  onSearchComplete,
}: {
  geoEnabled: boolean;
  geoLat: number | null;
  geoLng: number | null;
  geoRadiusKm: number;
  onConfigChange: (lat: number, lng: number, radiusKm: number) => void;
  onSearchComplete?: (result: GeoSearchResponse) => void;
}) {
  const defaultCenter: [number, number] = [57.15, 65.53];
  const [center, setCenter] = useState<[number, number]>(
    geoLat != null && geoLng != null ? [geoLat, geoLng] : defaultCenter
  );
  const [zoom, setZoom] = useState(geoLat != null ? 12 : 5);
  const [pin, setPin] = useState<[number, number] | null>(
    geoLat != null && geoLng != null ? [geoLat, geoLng] : null
  );
  const [radiusKm, setRadiusKm] = useState(geoRadiusKm);
  const [venues, setVenues] = useState<VenueResult[]>([]);
  const [myLocation, setMyLocation] = useState<[number, number] | null>(null);
  const [loading, setLoading] = useState(false);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  const [addrQuery, setAddrQuery] = useState("");
  const [addrSuggestions, setAddrSuggestions] = useState<GeoSuggestion[]>([]);
  const [showAddrSugg, setShowAddrSugg] = useState(false);
  const addrTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Sync props → local state
  useEffect(() => {
    if (geoLat != null && geoLng != null) {
      setPin([geoLat, geoLng]);
      setCenter([geoLat, geoLng]);
      setZoom(12);
    }
  }, [geoLat, geoLng]);

  useEffect(() => { setRadiusKm(geoRadiusKm); }, [geoRadiusKm]);

  // Fetch venues when pin/radius changes
  const fetchVenues = useCallback(async (lat: number, lng: number, km: number) => {
    setLoading(true); setError("");
    try {
      const res = await api.post<GeoSearchResult>("/discovery/geo-radius", { lat, lng, radius_km: km });
      setVenues(res.places);
    } catch (e) { setError((e as Error).message); setVenues([]); }
    setLoading(false);
  }, []);

  useEffect(() => {
    if (!pin) return;
    const t = setTimeout(() => fetchVenues(pin[0], pin[1], radiusKm), 300);
    return () => clearTimeout(t);
  }, [pin, radiusKm, fetchVenues]);

  const handleMapClick = useCallback((lat: number, lng: number) => {
    setPin([lat, lng]); setNote(""); setError("");
    onConfigChange(lat, lng, radiusKm);
  }, [onConfigChange, radiusKm]);

  // Address search
  const onAddrInput = (v: string) => {
    setAddrQuery(v);
    if (addrTimer.current) clearTimeout(addrTimer.current);
    if (v.trim().length < 2) { setAddrSuggestions([]); setShowAddrSugg(false); return; }
    addrTimer.current = setTimeout(async () => {
      try {
        const res = await api.get<GeoSuggestion[]>(`/discovery/geocode?q=${encodeURIComponent(v.trim())}`);
        setAddrSuggestions(res); setShowAddrSugg(true);
      } catch { /* best-effort */ }
    }, 350);
  };

  const pickAddrSuggestion = (s: GeoSuggestion) => {
    setPin([s.lat, s.lon]); setCenter([s.lat, s.lon]); setZoom(13);
    setAddrQuery(s.name || s.display_name.split(",")[0]);
    setAddrSuggestions([]); setShowAddrSugg(false); setNote(""); setError("");
    onConfigChange(s.lat, s.lon, radiusKm);
  };

  // My location
  const goMyLocation = () => {
    if (!navigator.geolocation) { setError("Geolocation not supported"); return; }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const loc: [number, number] = [pos.coords.latitude, pos.coords.longitude];
        setMyLocation(loc); setPin(loc); setCenter(loc); setZoom(13); setNote(""); setError("");
        onConfigChange(loc[0], loc[1], radiusKm);
      },
      () => setError("Could not determine your location."),
      { enableHighAccuracy: true, timeout: 10000 }
    );
  };

  // One-time search
  const runSearch = async () => {
    if (!pin) { setError("Click on the map or search for an address"); return; }
    setSearching(true); setError(""); setNote("");
    try {
      const res = await api.post<GeoSearchResponse>("/discovery/geo-search", {
        lat: pin[0], lng: pin[1], radius_km: radiusKm,
      });
      setNote(`Found ${res.venues_found} venues, added ${res.venues_added} new to search. Total locations: ${res.total_locations}`);
      onSearchComplete?.(res);
    } catch (e) { setError((e as Error).message); }
    setSearching(false);
  };

  // Radius change → persist
  const onRadiusChange = (v: number) => {
    setRadiusKm(v);
    if (pin) onConfigChange(pin[0], pin[1], v);
  };

  const circleRadius = radiusKm * 1000;

  return (
    <div className="space-y-3">
      {/* Address + My Location + Search */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <input value={addrQuery} onChange={(e) => onAddrInput(e.target.value)}
            onFocus={() => addrSuggestions.length > 0 && setShowAddrSugg(true)}
            onBlur={() => setTimeout(() => setShowAddrSugg(false), 200)}
            placeholder="Search address (e.g. Ленинский проспект 57)…"
            className="w-full rounded-xl border border-slate-300 bg-white pl-9 pr-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800" />
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
            className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>
          {showAddrSugg && addrSuggestions.length > 0 && (
            <div className="absolute z-20 mt-1 max-h-64 w-full overflow-auto rounded-xl border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-800">
              {addrSuggestions.map((s, i) => (
                <button key={i} onMouseDown={() => pickAddrSuggestion(s)}
                  className="block w-full px-3 py-2 text-left hover:bg-slate-100 dark:hover:bg-slate-700">
                  <span className="text-sm font-medium">{s.name}</span>
                  <div className="truncate text-xs text-slate-500 dark:text-slate-400">{s.display_name.split(",").slice(0, 3).join(",")}</div>
                </button>
              ))}
            </div>
          )}
        </div>
        <button onClick={goMyLocation}
          className="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
          title="My location">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
            <circle cx="12" cy="12" r="3" /><path d="M12 2v4m0 12v4M2 12h4m12 0h4" />
          </svg>
          My location
        </button>
        <button onClick={runSearch} disabled={searching || !pin}
          className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-sm shadow-emerald-600/30 transition-colors hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-300 dark:disabled:bg-slate-700">
          {searching ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
            : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>}
          {searching ? "Searching…" : "Search now"}
        </button>
      </div>

      {/* Radius */}
      <div className="flex items-center gap-3">
        <label className="text-xs font-medium text-slate-500 dark:text-slate-400 whitespace-nowrap">Radius:</label>
        <input type="range" min={1} max={50} step={1} value={radiusKm}
          onChange={(e) => onRadiusChange(Number(e.target.value))}
          className="h-2 flex-1 cursor-pointer appearance-none rounded-full bg-slate-200 accent-emerald-600 dark:bg-slate-700" />
        <span className="rounded-lg bg-emerald-50 px-2.5 py-1 text-sm font-semibold tabular-nums text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400 min-w-[52px] text-center">
          {radiusKm} km
        </span>
      </div>

      {/* Status */}
      {error && <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">{error}</div>}
      {note && <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">{note}</div>}

      {/* Map */}
      <div className="relative overflow-hidden rounded-xl border border-slate-200 dark:border-slate-800">
        <MapContainer center={center} zoom={zoom} className="z-0 h-[350px] w-full" scrollWheelZoom={true}>
          <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
          <FlyTo center={pin || center} zoom={pin ? Math.max(zoom, 12) : zoom} />
          <MapClickHandler onMapClick={handleMapClick} />

          {/* Radius circle */}
          {pin && <Circle center={pin} radius={circleRadius}
            pathOptions={{ color: geoEnabled ? "#6366f1" : "#10b981", fillColor: geoEnabled ? "#6366f1" : "#10b981", fillOpacity: 0.08, weight: 2 }} />}

          {/* Center pin */}
          {pin && (
            <Marker position={pin} icon={pinIcon}>
              <Popup><div className="text-sm">
                <div className="font-medium">Search center</div>
                <div className="text-xs text-slate-500">{pin[0].toFixed(5)}, {pin[1].toFixed(5)}</div>
              </div></Popup>
            </Marker>
          )}

          {/* My location */}
          {myLocation && <Marker position={myLocation} icon={myLocationIcon}><Popup><div className="text-sm font-medium">My location</div></Popup></Marker>}

          {/* Venues */}
          {venues.map((v) => (
            <Marker key={v.venue_id} position={[v.lat, v.long]} icon={venueIcon}>
              <Popup><div className="min-w-[160px]">
                <div className="text-sm font-semibold text-slate-900">{v.title}</div>
                {v.address && <div className="text-xs text-slate-500">{v.address}</div>}
                <div className="mt-1 text-xs font-medium text-emerald-600">{v.distance_km} km away</div>
              </div></Popup>
            </Marker>
          ))}
        </MapContainer>

        {venues.length > 0 && (
          <div className="absolute right-3 top-3 z-[1000] rounded-lg bg-white/90 px-3 py-1.5 text-xs font-medium text-slate-700 shadow dark:bg-slate-800/90 dark:text-slate-200">
            {loading ? "Loading…" : `${venues.length} venues in radius`}
          </div>
        )}
        {geoEnabled && (
          <div className="absolute left-3 top-3 z-[1000] rounded-lg bg-indigo-600/90 px-3 py-1.5 text-xs font-medium text-white shadow">
            🔁 Auto-search active
          </div>
        )}
      </div>

      {/* Venue list */}
      {venues.length > 0 && (
        <div className="rounded-xl border border-slate-200 dark:border-slate-800">
          <div className="border-b border-slate-100 px-4 py-2.5 dark:border-slate-800">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Venues in radius ({venues.length})
            </span>
          </div>
          <div className="max-h-48 divide-y divide-slate-100 overflow-auto dark:divide-slate-800">
            {venues.map((v) => (
              <div key={v.venue_id} className="flex items-center gap-3 px-4 py-2 hover:bg-slate-50 dark:hover:bg-slate-800/50">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-xs font-bold text-amber-700 dark:bg-amber-500/10 dark:text-amber-400">{v.distance_km}</span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-slate-700 dark:text-slate-200">{v.title}</div>
                  {v.address && <div className="truncate text-xs text-slate-400">{v.address}</div>}
                </div>
                <span className="text-xs text-slate-400">km</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {!pin && <p className="text-xs text-slate-400 text-center">Click on the map or search for an address to set the search center</p>}
    </div>
  );
}
