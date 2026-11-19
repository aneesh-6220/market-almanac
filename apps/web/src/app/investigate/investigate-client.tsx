"use client";

import { useUrlState } from "@/lib/url-state";

import { Discovery } from "./discovery";
import { InvestigationView } from "./investigation-view";

/** One route, two views: discovery (no `series`) and the investigation of one series (with `series`). */
export function InvestigateClient() {
  const { get } = useUrlState();
  const series = get("series");
  return series ? <InvestigationView seriesId={series} /> : <Discovery />;
}
