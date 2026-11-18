"use client";

import Link from "next/link";

import { StudyView } from "@/components/study-view";
import { Empty, ErrorState, Loading, Panel, Tag } from "@/components/ui";
import { dateTime } from "@/lib/format";
import { useStudies } from "@/lib/research-api";
import { useUrlState } from "@/lib/url-state";

export function StudiesClient() {
  const { get, set } = useUrlState();
  const id = get("id");
  const list = useStudies();
  if (id)
    return (
      <div className="space-y-4">
        <button
          type="button"
          className="text-sm text-rain underline-offset-4 hover:underline"
          onClick={() => set({ id: null })}
        >
          ← All studies
        </button>
        <StudyView id={id} />
      </div>
    );
  if (list.isLoading) return <Loading label="Loading studies" />;
  if (list.error)
    return <ErrorState error={list.error} what="published studies" />;
  return (
    <div className="space-y-4">
      <ul className="grid gap-4 md:grid-cols-2">
        <li>
          <article className="h-full rounded-md border border-line bg-surface p-5">
            <div className="flex flex-wrap gap-2">
              <Tag tone="good">confirmatory</Tag>
              <Tag>predictive</Tag>
              <Tag tone="good">frozen before estimation</Tag>
            </div>
            <h2 className="mt-3 text-lg font-semibold text-ink">
              <Link href="/lab" className="hover:underline">
                Sahel production weather v1
              </Link>
            </h2>
            <p className="mt-1 text-sm text-ink-2">
              The original single-region study (Mali, Niger, Burkina Faso): do
              growing-season weather anomalies in production zones improve
              millet and sorghum price forecasts? Archived results and audit
              scripts are preserved unchanged.
            </p>
            <p className="mt-2 text-xs text-ink-3">
              Tag protocol-sahel-v1 · results in the Research Lab
            </p>
          </article>
        </li>
        {(list.data ?? []).map((s) => (
          <li key={s.id}>
            <article className="h-full rounded-md border border-line bg-surface p-5">
              <div className="flex flex-wrap gap-2">
                <Tag
                  tone={s.evidence_class === "confirmatory" ? "good" : "muted"}
                >
                  {s.evidence_class}
                </Tag>
                <Tag>{s.study_type}</Tag>
                {s.frozen && <Tag tone="good">frozen before estimation</Tag>}
              </div>
              <h2 className="mt-3 text-lg font-semibold text-ink">
                <button
                  type="button"
                  className="text-left hover:underline"
                  onClick={() => set({ id: s.id })}
                >
                  {s.title}
                </button>
              </h2>
              <p className="mt-1 text-sm text-ink-2">{s.headline}</p>
              <p className="mt-2 text-xs text-ink-3">
                {s.n_countries ?? "—"} countries · published{" "}
                {dateTime(s.published_at)} · spec {s.spec_hash.slice(0, 12)}
              </p>
            </article>
          </li>
        ))}
      </ul>
      {!list.data?.length && (
        <Empty>
          No workbench studies are published on this deployment yet.
        </Empty>
      )}
      <Panel title="Adding a study">
        <p className="text-sm text-ink-2">
          Studies are written as versioned specifications, checked in the{" "}
          <Link className="underline" href="/workbench">
            workbench
          </Link>
          , run locally with the command-line tool and published as a hashed
          package. The public site never executes analyses.
        </p>
      </Panel>
    </div>
  );
}
