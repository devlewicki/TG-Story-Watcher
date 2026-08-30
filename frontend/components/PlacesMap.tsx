"use client";

import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import "leaflet.markercluster/dist/MarkerCluster.Default.css";

export type MapPlace = {
  id: number;
  venue_id: string;
  title: string;
  address: string | null;
  lat: number | null;
  long: number | null;
};

function pinIcon(selected: boolean): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `<div class="sw-pin ${selected ? "sw-pin--selected" : ""}">
      <svg viewBox="0 0 24 24" fill="currentColor" class="sw-pin__icon">
        <path d="M12 2a7 7 0 0 0-7 7c0 5.2 7 13 7 13s7-7.8 7-13a7 7 0 0 0-7-7zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5z"/>
      </svg>
    </div>`,
    iconSize: [30, 34],
    iconAnchor: [15, 32],
    popupAnchor: [0, -30],
  });
}

/* Dark-mode aware tile toggle handled by re-render on theme via key. */

export default function PlacesMap({
  places,
  selectedVids,
  onToggle,
}: {
  places: MapPlace[];
  selectedVids: Set<string>;
  onToggle: (p: MapPlace) => void;
}) {
  // Default center: a place (or fallback) so the map opens somewhere useful.
  const first = places.find((p) => p.lat != null && p.long != null);
  const center: [number, number] =
    first && first.lat != null && first.long != null
      ? [first.lat, first.long]
      : [57.15, 65.53]; // Russia
  const zoom = first ? 10 : 4;

  return (
    <MapContainer
      center={center}
      zoom={zoom}
      className="z-0 h-[420px] w-full rounded-xl"
      scrollWheelZoom={false}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <MarkerClusterGroup
        chunkedLoading
        showCoverageOnHover={false}
        spiderfyOnMaxZoom
      >
        {places.map((p) => {
          if (p.lat == null || p.long == null) return null;
          const selected = selectedVids.has(p.venue_id);
          return (
            <Marker
              key={p.venue_id}
              position={[p.lat, p.long]}
              icon={pinIcon(selected)}
            >
              <Popup>
                <div className="min-w-[180px]">
                  <div className="mb-1 text-sm font-semibold text-slate-900">{p.title}</div>
                  {p.address && (
                    <div className="mb-2 text-xs text-slate-500">{p.address}</div>
                  )}
                  <button
                    onClick={() => onToggle(p)}
                    className={`w-full rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                      selected
                        ? "bg-slate-200 text-slate-700 hover:bg-slate-300"
                        : "bg-emerald-600 text-white hover:bg-emerald-700"
                    }`}
                  >
                    {selected ? "✓ В поиске — убрать" : "Искать здесь"}
                  </button>
                </div>
              </Popup>
            </Marker>
          );
        })}
      </MarkerClusterGroup>
    </MapContainer>
  );
}