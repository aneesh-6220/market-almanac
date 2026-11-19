import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { InvestigateClient } from "./investigate-client";

export const metadata: Metadata = {
  title: "Price shock investigator",
  description:
    "Find unusual food-price movements across 95 countries and investigate one: how unusual it was, whether comparable markets and other foods moved too, what context exists, and what the data cannot say.",
};

export default function Page() {
  return (
    <Suspense fallback={<Loading label="Loading the investigator" />}>
      <InvestigateClient />
    </Suspense>
  );
}
