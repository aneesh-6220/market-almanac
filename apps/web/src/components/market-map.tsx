"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import maplibregl, { type GeoJSONSource, type StyleSpecification } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import type { Market } from "@/lib/api";

const STYLE_URL = process.env.NEXT_PUBLIC_MAP_STYLE_URL || "https://tiles.openfreemap.org/styles/positron";

// Used when the tile provider is unreachable (e.g. offline demo): markets still plot, without a basemap.
const FALLBACK_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#dfe6ec" } }],
};

function toGeoJSON(markets: Market[], selected?: string) {
  return {
    type: "FeatureCollection" as const,
    features: markets
      .filter((m) => m.lat !== null && m.lon !== null)
      .map((m) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [m.lon as number, m.lat as number] },
        properties: { id: m.id, name: m.name, eligible: m.eligible_series > 0 ? 1 : 0, selected: m.id === selected ? 1 : 0, n: m.n_series },
      })),
  };
}

export function MarketMap({ markets, selected, onSelect }: { markets: Market[]; selected?: string; onSelect: (id: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const [basemapFailed, setBasemapFailed] = useState(false);
  const onSelectRef = useRef(onSelect);
  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  useEffect(() => {
    if (!box.current) return;
    const m = new maplibregl.Map({ container: box.current, style: STYLE_URL, center: [20, 5], zoom: 2, attributionControl: { compact: true } });
    map.current = m;
    let fellBack = false;
    m.on("error", (e) => {
      if (!fellBack && !m.isStyleLoaded() && String(e.error?.message ?? "").length) {
        fellBack = true;
        setBasemapFailed(true);
        m.setStyle(FALLBACK_STYLE);
      }
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    const setup = () => {
      if (m.getSource("markets")) return;
      const css = getComputedStyle(document.documentElement);
      const grain = css.getPropertyValue("--grain").trim() || "#b97d12";
      const ink = css.getPropertyValue("--ink").trim() || "#18233a";
      m.addSource("markets", { type: "geojson", data: toGeoJSON([]) });
      m.addLayer({
        id: "markets",
        type: "circle",
        source: "markets",
        paint: {
          "circle-radius": ["case", ["==", ["get", "selected"], 1], 9, 6],
          "circle-color": ["case", ["==", ["get", "eligible"], 1], grain, "#ffffff"],
          "circle-stroke-color": ["case", ["==", ["get", "selected"], 1], ink, ["==", ["get", "eligible"], 1], "#ffffff", "#6f7d93"],
          "circle-stroke-width": ["case", ["==", ["get", "selected"], 1], 2.5, 1.5],
        },
      });
      m.on("click", "markets", (e) => {
        const id = e.features?.[0]?.properties?.id;
        if (id) onSelectRef.current(String(id));
      });
      m.on("mouseenter", "markets", () => (m.getCanvas().style.cursor = "pointer"));
      m.on("mouseleave", "markets", () => (m.getCanvas().style.cursor = ""));
      setReady(true);
    };
    m.on("style.load", setup);
    return () => {
      m.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m || !ready) return;
    (m.getSource("markets") as GeoJSONSource | undefined)?.setData(toGeoJSON(markets, selected));
  }, [markets, selected, ready]);

  useEffect(() => {
    const m = map.current;
    const pts = markets.filter((x) => x.lat !== null && x.lon !== null);
    if (!m || !ready || !pts.length) return;
    const b = new maplibregl.LngLatBounds();
    pts.forEach((p) => b.extend([p.lon as number, p.lat as number]));
    m.fitBounds(b, { padding: 60, maxZoom: 7, duration: 0 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, markets.map((x) => x.id).join()]);

  return (
    <div className="relative">
      <div ref={box} className="h-[420px] w-full overflow-hidden rounded-md border border-line md:h-[520px]" aria-label="Map of markets with price data" role="region" />
      <div className="pointer-events-none absolute bottom-2 left-2 rounded bg-surface/90 px-2 py-1.5 text-xs text-ink-2 shadow-sm">
        <span className="mr-3 inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: "var(--grain)" }} /> has a forecastable series
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full border border-ink-3 bg-white" /> data too sparse
        </span>
      </div>
      {basemapFailed && (
        <p className="mt-1 text-xs text-ink-3">Basemap tiles could not be loaded; markets are plotted without a background map.</p>
      )}
    </div>
  );
}
