import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { DataClient } from "./data-client";

export const metadata: Metadata = { title: "Data quality and provenance" };

export default function Page() {
  return (
    <Suspense fallback={<Loading label="Loading data status" />}>
      <DataClient />
    </Suspense>
  );
}
