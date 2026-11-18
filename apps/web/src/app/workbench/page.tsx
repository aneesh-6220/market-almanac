import type { Metadata } from "next";

import { PageHeader } from "@/components/ui";

import { WorkbenchClient } from "./workbench-client";

export const metadata: Metadata = {
  title: "Research workbench",
  description:
    "Build and validate a versioned research specification, then run it reproducibly with the command-line tool.",
};

export default function Page() {
  return (
    <>
      <PageHeader
        title="Research workbench"
        lede="Write a study as a specification: population, timing, hypotheses, inference and controls. The server checks it for scientific coherence; running it is a local, reproducible command. Nothing is executed on this site."
      />
      <WorkbenchClient />
    </>
  );
}
