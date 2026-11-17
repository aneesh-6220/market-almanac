import type { Metadata } from "next";

export const metadata: Metadata = { title: "About" };

const SOURCES = [
  ["Market prices", "WFP food prices via HDX HAPI (Humanitarian Data Exchange)", "CC BY-IGO; cite WFP VAM and HDX"],
  ["Weather", "NASA POWER daily agroclimatology", "Public; cite the NASA Langley Research Center POWER Project"],
  ["Development indicators", "World Bank Indicators API (WDI)", "CC BY 4.0"],
  ["Prices and exchange rates", "IMF SDMX data API (CPI, exchange rates)", "IMF terms of use; cite the IMF"],
  ["Crop production", "FAOSTAT production (QCL)", "CC BY 4.0; cite FAO"],
];

export default function About() {
  return (
    <div className="grid gap-12 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <article className="prose-st">
        <h1 className="font-serif text-4xl leading-tight text-ink md:text-5xl">About ShockTrace</h1>
        <p className="mt-4 text-xl">
          ShockTrace is an open-source research platform for testing whether weather anomalies help forecast food-price
          changes and spikes. It is built for analysts, researchers and students who want results they can inspect,
          reproduce and challenge.
        </p>

        <h2>What it is for</h2>
        <p>
          Exploring market price histories alongside local weather and national context; running pre-specified,
          leakage-safe forecasting experiments; and publishing the evidence, including null and inconclusive results, with
          every data snapshot and setting recorded.
        </p>

        <h2>What it is not for</h2>
        <ul>
          <li>Operational early warning or humanitarian targeting without independent validation.</li>
          <li>Trading or investment decisions. Nothing here is financial advice.</li>
          <li>Causal claims about weather and prices. The method measures predictive value only.</li>
        </ul>

        <h2>Demo and live modes</h2>
        <p>
          Demo mode runs entirely offline on synthetic data for a fictional country, &ldquo;Demoland&rdquo;, with its own
          currency code. Everything in demo mode is marked with a hatched &ldquo;synthetic&rdquo; band. Live mode uses
          only data retrieved from the five providers and never substitutes synthetic values when a provider fails.
        </p>

        <h2>Open source</h2>
        <p>
          The code is released under the MIT licence. Data remain under their providers&rsquo; licences, listed alongside.
          Contributions are welcome: see <code>CONTRIBUTING.md</code> for the development setup, test suite and the
          scientific-correctness checks every change must pass, and <code>SECURITY.md</code> for reporting
          vulnerabilities.
        </p>

        <h2>Citing</h2>
        <p>
          If you use ShockTrace results, cite the experiment ID and its manifest (data snapshot IDs, configuration hash and
          software version), and the original data providers.
        </p>
      </article>

      <aside className="lg:pt-24">
        <h2 className="mb-3 text-base font-semibold text-ink">Data licences</h2>
        <dl className="divide-y divide-line border-y border-line text-sm">
          {SOURCES.map(([what, src, lic]) => (
            <div key={what} className="py-3">
              <dt className="font-medium text-ink">{what}</dt>
              <dd className="mt-0.5 text-ink-2">{src}</dd>
              <dd className="mt-0.5 text-ink-3">{lic}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-4 text-sm text-ink-3">
          Licence terms are summarised; check each provider&rsquo;s current terms before redistribution. Base map tiles are
          attributed on the map itself.
        </p>
      </aside>
    </div>
  );
}
