import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { ExplorerClient } from "./explorer-client";

export const metadata: Metadata = { title: "Global explorer" };

export default function Page() {
  return (
    <Suspense fallback={<Loading label="Loading explorer" />}>
      <ExplorerClient />
    </Suspense>
  );
}
