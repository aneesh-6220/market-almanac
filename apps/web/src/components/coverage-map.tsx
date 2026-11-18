"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import { type GeoJSONSource, Map as MapLibreMap, type MapOptions, NavigationControl, setWorkerUrl } from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";

import { type CoverageStatus, type MarketIndex, STATUS_ORDER, STATUS_STYLE } from "@/lib/research-api";

setWorkerUrl(new URL("maplibre-gl/dist/maplibre-gl-worker.mjs", import.meta.url).href);

const STYLE_URL = process.env.NEXT_PUBLIC_MAP_STYLE_URL || "https://tiles.openfreemap.org/styles/positron";
type StyleSpecification = Exclude<MapOptions["style"], string | undefined>;
const FALLBACK_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#dfe6ec" } }],
};

/**
 * Every stored WFP market, coloured by its country's coverage status. Countries with no integrated
 * price source have no points: the gaps on this map are real gaps in the data, not missing styling.
 */
export function CoverageMap({
  index,
  statusByCountry,
  selected,
  onSelect,
}: {
  index: MarketIndex;
  statusByCountry: Record<string, CoverageStatus>;
  selected?: string;
  onSelect: (iso3: string) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const onSelectRef = useRef(onSelect);
  const [ready, setReady] = useState(false);
  const [basemapFailed, setBasemapFailed] = useState(false);
  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  const geojson = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: index.rows.map(([iso, code, name, lat, lon, series, last]) => ({
        type: "Feature" as const,
        geometry: { type: "Point" as const, coordinates: [lon, lat] },
        properties: {
          iso,
          code,
          name,
          series,
          last,
          status: statusByCountry[iso] ?? "ingested",
          selected: iso === selected ? 1 : 0,
        },
      })),
    }),
    [index, statusByCountry, selected],
  );

  useEffect(() => {
    if (!box.current || map.current) return;
    const m = new MapLibreMap({
      container: box.current,
      style: STYLE_URL,
      center: [25, 12],
      zoom: 1.3,
      attributionControl: { compact: true },
      cooperativeGestures: true,
    });
    map.current = m;
    let fellBack = false;
    m.on("error", (e) => {
      if (!fellBack && !m.isStyleLoaded() && String(e.error?.message ?? "").length) {
        fellBack = true;
        setBasemapFailed(true);
        m.setStyle(FALLBACK_STYLE);
      }
    });
    m.addControl(new NavigationControl({ showCompass: false }), "top-right");
    const setup = () => {
      if (m.getSource("markets")) return;
      m.addSource("markets", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      const color: unknown[] = ["match", ["get", "status"]];
      for (const s of STATUS_ORDER) color.push(s, STATUS_STYLE[s].color);
      color.push("#888888");
      m.addLayer({
        id: "markets",
        type: "circle",
        source: "markets",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 2.2, 5, 4.5, 8, 7],
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          "circle-color": color as any,
          "circle-opacity": ["case", ["==", ["get", "selected"], 1], 1, 0.8],
          "circle-stroke-color": ["case", ["==", ["get", "selected"], 1], "#18233a", "#ffffff"],
          "circle-stroke-width": ["case", ["==", ["get", "selected"], 1], 1.4, 0.4],
        },
      });
      m.on("click", "markets", (e) => {
        const iso = e.features?.[0]?.properties?.iso;
        if (iso) onSelectRef.current(String(iso));
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
    (m.getSource("markets") as GeoJSONSource | undefined)?.setData(geojson);
  }, [geojson, ready]);

  const present = STATUS_ORDER.filter((s) => s !== "unsupported" && Object.values(statusByCountry).includes(s));
  return (
    <div className="relative">
      <div
        ref={box}
        className="h-[380px] w-full overflow-hidden rounded-md border border-line md:h-[500px]"
        role="region"
        aria-label={`World map of ${index.rows.length} markets with stored WFP prices, coloured by country coverage status. The country table below lists the same information.`}
      />
      <div className="pointer-events-none absolute bottom-2 left-2 max-w-[calc(100%-1rem)] rounded bg-surface/90 px-2 py-1.5 text-xs text-ink-2 shadow-sm">
        {present.map((s) => (
          <span key={s} className="mr-3 inline-flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: STATUS_STYLE[s].color }} aria-hidden />
            {STATUS_STYLE[s].label}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">no points: no integrated price source</span>
      </div>
      {basemapFailed && <p className="mt-1 text-xs text-ink-3">Basemap tiles could not be loaded; markets are plotted without a background map.</p>}
    </div>
  );
}
