import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { ForecastsClient } from "./forecasts-client";

export const metadata: Metadata = { title: "Forecast explorer" };

export default function Page() {
  return (
    <Suspense fallback={<Loading label="Loading forecasts" />}>
      <ForecastsClient />
    </Suspense>
  );
}
