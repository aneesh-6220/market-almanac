import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { CompareClient } from "./compare-client";

export const metadata: Metadata = {
  title: "Compare markets",
  description: "Compare the price of the same commodity across markets, in levels where valid and as indexed movements.",
};

export default function Page() {
  return (
    <Suspense fallback={<Loading label="Loading comparison" />}>
      <CompareClient />
    </Suspense>
  );
}
