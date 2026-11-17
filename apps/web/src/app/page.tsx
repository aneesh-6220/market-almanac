import Link from "next/link";

import { SourceList } from "@/components/home-evidence";
import { HomeCoverage, HomeMovers, HomeSearch } from "@/components/home-live";
import { StudyPanel } from "@/components/study-panel";
import { ButtonLink } from "@/components/ui";

const PILLARS = [
  {
    title: "Food-price intelligence",
    body: "Monthly market prices by country, commodity and market, each shown with the month it was observed, its unit and its source. See what moved, by how much, and whether that is unusual for the series.",
    href: "/explorer",
    cta: "Explore markets",
  },
  {
    title: "Environment and markets",
    body: "Rainfall and temperature near each market and across the areas where the crop is grown, aligned with the growing season. Shown as context, with the limits of what a correlation can tell you.",
    href: "/methodology",
    cta: "How it is measured",
  },
  {
    title: "Forecast accountability",
    body: "Every model is scored on data it never saw and compared with simple benchmarks. Forecasts are shown only when they have been evaluated, and negative results are published in full.",
    href: "/lab",
    cta: "Open the Research Lab",
  },
];

export default function Home() {
  return (
    <div>
      <section className="grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] lg:gap-14">
        <div className="pt-2">
          <h1 className="font-serif text-5xl leading-[1.05] text-ink md:text-6xl">What are food prices doing, and can anyone forecast them?</h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-ink-2">
            ShockTrace turns public market-price, weather and crop data into evidence you can check: price histories, unusual movements, market comparisons, and an honest account
            of what forecasting models can and cannot do.
          </p>
          <HomeSearch />
          <div className="mt-4 flex flex-wrap gap-3">
            <ButtonLink href="/compare" variant="quiet">
              Compare markets
            </ButtonLink>
            <ButtonLink href="/data" variant="quiet">
              See data coverage
            </ButtonLink>
          </div>
        </div>
        <HomeCoverage />
      </section>

      <section className="mt-20 grid grid-cols-[minmax(0,1fr)] gap-8 md:grid-cols-3">
        {PILLARS.map((p) => (
          <div key={p.title} className="border-t-2 border-ink pt-4">
            <h2 className="font-serif text-2xl text-ink">{p.title}</h2>
            <p className="mt-3 text-ink-2">{p.body}</p>
            <Link href={p.href} className="mt-3 inline-block text-sm font-medium text-rain underline-offset-4 hover:underline">
              {p.cta}
            </Link>
          </div>
        ))}
      </section>

      <section className="mt-20 grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <div>
          <h2 className="font-serif text-3xl text-ink">Unusual recent movements</h2>
          <p className="mt-3 text-sm text-ink-3">
            Series whose latest monthly change is large compared with their own history. A statistical description, not a signal of shortage or crisis.
          </p>
        </div>
        <HomeMovers />
      </section>

      <section className="mt-20 grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <div>
          <h2 className="font-serif text-3xl text-ink">What the research found</h2>
          <p className="mt-3 text-sm text-ink-3">The design was fixed and tagged before the models were run on the countries used for the test.</p>
        </div>
        <StudyPanel compact />
      </section>

      <section className="mt-20 grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <h2 className="font-serif text-3xl text-ink">What this can and cannot tell you</h2>
        <div className="grid gap-8 md:grid-cols-2">
          <div>
            <h3 className="font-medium text-good">It can show</h3>
            <ul className="mt-3 space-y-3 text-ink-2">
              <li>What a market reported, for which month, in which unit and currency.</li>
              <li>How a movement compares with that series&rsquo; own past, and whether other markets moved too.</li>
              <li>Whether a forecasting model beat simple benchmarks on data it had never seen.</li>
              <li>Where the data are thin, late or flagged, so you can discount accordingly.</li>
            </ul>
          </div>
          <div>
            <h3 className="font-medium text-bad">It cannot show</h3>
            <ul className="mt-3 space-y-3 text-ink-2">
              <li>Why a price moved. Nothing here identifies causes, and an unusual movement is not a confirmed shortage.</li>
              <li>Living costs across countries. Nominal prices in different currencies are not converted or compared in level.</li>
              <li>What a forecaster knew in real time. Sources do not publish release dates, so timing rests on stated assumptions.</li>
              <li>The world. Coverage is the set of countries ingested here, not the whole WFP dataset.</li>
            </ul>
          </div>
        </div>
      </section>

      <section className="mt-20 grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <h2 className="font-serif text-3xl text-ink">Sources</h2>
        <div>
          <p className="mb-5 max-w-2xl text-ink-2">
            Public data, fetched through documented APIs, stored as immutable snapshots and shown with retrieval dates and licences. Crop-area weights come from IFPRI MapSPAM 2010
            and crop calendars from the World Bank / JRC Africa crop calendar.
          </p>
          <SourceList />
        </div>
      </section>

      <section className="mt-20 grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <h2 className="font-serif text-3xl text-ink">Open source, reproducible</h2>
        <div className="max-w-2xl">
          <p className="text-ink-2">
            The code, the research protocol and every result table are in the repository. The demo runs offline with synthetic data and no credentials; the API is public and
            read-only.
          </p>
          <pre className="mt-4 overflow-x-auto rounded-md bg-ink p-4 text-sm leading-relaxed text-bg">
{`make demo                              # synthetic demo, no credentials
curl "$API/api/v1/catalog/series?q=millet&country=MLI"
shocktrace study --phase confirmatory  # re-run the pre-registered study`}
          </pre>
        </div>
      </section>
    </div>
  );
}
