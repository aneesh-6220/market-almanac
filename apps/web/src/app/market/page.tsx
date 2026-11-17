import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { MarketClient } from "./market-client";

export const metadata: Metadata = { title: "Market analysis" };

export default function Page() {
  return (
    <Suspense fallback={<Loading label="Loading market" />}>
      <MarketClient />
    </Suspense>
  );
}
