import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading } from "@/components/ui";

import { LabClient } from "./lab-client";

export const metadata: Metadata = { title: "Model laboratory" };

export default function Page() {
  return (
    <Suspense fallback={<Loading label="Loading experiment" />}>
      <LabClient />
    </Suspense>
  );
}
