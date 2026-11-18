import type { Metadata } from "next";

import { PageHeader } from "@/components/ui";

import { ForecastabilityClient } from "./forecastability-client";

export const metadata: Metadata = {
  title: "Forecastability Atlas",
  description:
    "Confirmatory, pre-registered test of whether market-local weather improves staple-food price forecasts across countries.",
};

export default function Page() {
  return (
    <>
      <PageHeader
        title="Forecastability Atlas"
        lede="A pre-registered, multi-country test: does market-local rainfall and temperature help forecast staple-food prices beyond price history? Frozen before any model was estimated; results are reported whichever way they came out."
      />
      <ForecastabilityClient />
    </>
  );
}
