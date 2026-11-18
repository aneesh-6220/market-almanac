"use client";

import Link from "next/link";

import { StudyView } from "@/components/study-view";
import { Empty, ErrorState, Loading } from "@/components/ui";
import { useStudies } from "@/lib/research-api";

export const ATLAS_ID = "forecastability-atlas-v1";

export function ForecastabilityClient() {
  const list = useStudies();
  if (list.isLoading) return <Loading label="Loading studies" />;
  if (list.error)
    return <ErrorState error={list.error} what="published studies" />;
  if (!list.data?.some((s) => s.id === ATLAS_ID))
    return (
      <Empty>
        The atlas has been frozen but its results are not published on this
        deployment yet. The protocol is in{" "}
        <a
          className="underline"
          href="https://github.com/aneesh-6220/market-almanac/blob/main/docs/research/FORECASTABILITY_ATLAS_PROTOCOL.md"
        >
          docs/research
        </a>
        ; other studies are in the{" "}
        <Link className="underline" href="/studies">
          study library
        </Link>
        .
      </Empty>
    );
  return <StudyView id={ATLAS_ID} />;
}
