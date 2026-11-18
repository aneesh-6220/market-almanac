import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { AtlasClient } from "./atlas-client";

export const metadata: Metadata = {
  title: "Global coverage",
  description:
    "Coverage status of every country: stored WFP prices, quality checks, eligibility and evaluations.",
};

export default function Page() {
  return (
    <Suspense fallback={<Loading label="Loading coverage" />}>
      <AtlasClient />
    </Suspense>
  );
}
