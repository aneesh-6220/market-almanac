import { HomeEvidence, SourceList } from "@/components/home-evidence";
import { ButtonLink } from "@/components/ui";

export default function Home() {
  return (
    <div>
      <section className="grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] lg:gap-14">
        <div className="pt-2">
          <h1 className="font-serif text-5xl leading-[1.05] text-ink md:text-6xl">
            Does last season&rsquo;s weather tell us anything about next month&rsquo;s food prices?
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-ink-2">
            ShockTrace tests whether rainfall and temperature anomalies improve out-of-sample forecasts of food-price
            changes and price spikes, beyond what price history and the economy already tell us. It reports the answer
            either way, with the uncertainty attached.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <ButtonLink href="/explorer">Explore markets</ButtonLink>
            <ButtonLink href="/methodology" variant="quiet">
              Read the method
            </ButtonLink>
          </div>
        </div>
        <HomeEvidence />
      </section>

      <section className="mt-24 grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <h2 className="font-serif text-3xl text-ink">Why price shocks matter</h2>
        <div className="prose-st">
          <p>
            For households that spend a large share of income on food, a sudden rise in the price of a staple can force
            hard trade-offs within weeks. Humanitarian agencies, ministries and buyers monitor market prices for exactly
            this reason, and many of them ask whether droughts, poor rains or heat waves give advance warning.
          </p>
          <p>
            That question is easy to answer badly. A correlation in hindsight is not a forecast, and a model that looks
            good on the data it was fitted to may fail on the next season. ShockTrace treats it as an out-of-sample
            prediction problem with strict timing rules, honest baselines and formal tests.
          </p>
        </div>
      </section>

      <section className="mt-20 grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <h2 className="font-serif text-3xl text-ink">What goes in</h2>
        <div>
          <p className="mb-5 max-w-2xl text-ink-2">
            Five official sources, each fetched through a documented API, versioned in immutable snapshots, and shown with
            its retrieval date and licence.
          </p>
          <SourceList />
        </div>
      </section>

      <section className="mt-20 grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <h2 className="font-serif text-3xl text-ink">What the model can and cannot tell you</h2>
        <div className="grid gap-8 md:grid-cols-2">
          <div>
            <h3 className="font-medium text-good">It can establish</h3>
            <ul className="mt-3 space-y-3 text-ink-2">
              <li>Whether adding weather information reduced forecast errors on data the model had never seen.</li>
              <li>How large that improvement was, with a confidence interval that respects time dependence.</li>
              <li>Whether the improvement held in both halves of the test period and across model specifications.</li>
              <li>When the data are too thin to say anything at all.</li>
            </ul>
          </div>
          <div>
            <h3 className="font-medium text-bad">It cannot establish</h3>
            <ul className="mt-3 space-y-3 text-ink-2">
              <li>That weather caused a price change. Better prediction is not a causal estimate.</li>
              <li>Conditions where the crop was grown. Weather is measured near the market, a geographic proxy.</li>
              <li>What a forecaster would have known in real time. Inputs are today&rsquo;s data vintage with conservative lags.</li>
              <li>Anything about trading. Forecasts are research outputs, not recommendations.</li>
            </ul>
          </div>
        </div>
      </section>

      <section className="mt-20 grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <h2 className="font-serif text-3xl text-ink">Reproduce it</h2>
        <div className="max-w-2xl">
          <p className="text-ink-2">
            Every experiment saves its configuration, data snapshot IDs, seeds and software versions. Re-run any result
            from the command line and ShockTrace reports whether the inputs and metrics match.
          </p>
          <pre className="mt-4 overflow-x-auto rounded-md bg-ink p-4 text-sm leading-relaxed text-bg">
{`make demo                                       # synthetic demo, no credentials
shocktrace discover --mode live --country BFA   # rank series by usable data
shocktrace ingest --mode live --source all --country BFA
shocktrace backtest --mode live --country BFA --commodity 67
shocktrace reproduce <experiment-id> --mode live`}
          </pre>
        </div>
      </section>
    </div>
  );
}
