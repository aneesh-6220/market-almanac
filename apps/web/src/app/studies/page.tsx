import type { Metadata } from "next";
import { Suspense } from "react";

import { Loading, PageHeader } from "@/components/ui";

import { StudiesClient } from "./studies-client";

export const metadata: Metadata = {
  title: "Study library",
  description:
    "Every published Market Almanac study, with its evidence class, frozen specification and downloadable results.",
};

export default function Page() {
  return (
    <>
      <PageHeader
        title="Study library"
        lede="Published studies with their specifications, provenance and results. Confirmatory studies were frozen before estimation; exploratory and descriptive studies are labelled as such."
      />
      <Suspense fallback={<Loading label="Loading studies" />}>
        <StudiesClient />
      </Suspense>
    </>
  );
}
