import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Research and methodology" };

const SECTIONS = [
  ["question", "The question"],
  ["data", "Data and units"],
  ["timing", "What was known when"],
  ["targets", "Forecast targets"],
  ["features", "Features"],
  ["models", "Models"],
  ["backtest", "Rolling-origin backtest"],
  ["metrics", "Scoring"],
  ["inference", "Is the difference real?"],
  ["verdicts", "From tests to verdicts"],
  ["forecasts", "Forward forecasts"],
  ["limits", "What this does not show"],
] as const;

function F({ children }: { children: React.ReactNode }) {
  return <div className="formula" role="math">{children}</div>;
}

function Example({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <aside className="my-6 rounded-md border border-line bg-surface p-5 font-sans text-base leading-relaxed" aria-label={`Worked example: ${title}`}>
      <div className="mb-2 text-sm font-semibold text-grain">Worked example · {title}</div>
      <div className="space-y-2 text-ink-2">{children}</div>
    </aside>
  );
}

export default function Methodology() {
  return (
    <div className="grid gap-12 lg:grid-cols-[14rem_minmax(0,1fr)]">
      <nav aria-label="On this page" className="hidden lg:block">
        <ol className="sticky top-24 space-y-1.5 text-sm">
          {SECTIONS.map(([id, label]) => (
            <li key={id}>
              <a href={`#${id}`} className="text-ink-3 hover:text-ink">
                {label}
              </a>
            </li>
          ))}
        </ol>
      </nav>
      <article className="prose-st">
        <h1 className="font-serif text-4xl leading-tight text-ink md:text-5xl">Research and methodology</h1>
        <p className="mt-4 text-xl">
          How ShockTrace turns five public datasets into a falsifiable answer, and the rules that keep it from fooling
          itself. The full technical write-up, with references, is in <code>docs/METHODOLOGY.md</code>.
        </p>

        <h2 id="question">The question</h2>
        <p>
          Do observed weather anomalies improve <em>out-of-sample</em> prediction of future food-price changes and price
          spikes, beyond what conventional price, seasonal and macroeconomic predictors already provide?
        </p>
        <p>
          This is a predictive question, not a causal one. A &ldquo;yes&rdquo; means that a model given weather
          information made smaller errors on months it had never seen. It does not mean that weather caused those prices,
          and a &ldquo;no&rdquo; does not mean weather is irrelevant to food markets: it may already be reflected in prices,
          or the market-local proxy may be too coarse.
        </p>

        <h2 id="data">Data and units</h2>
        <p>
          The unit of analysis is one <strong>comparable price series</strong>: a single market, commodity, unit, price
          type (retail or wholesale) and currency from the WFP food-price records served by HDX HAPI. Series that differ in
          any of these are never merged, and no price is converted between units or currencies.
        </p>
        <ul>
          <li>Weather: NASA POWER daily rainfall and temperature for the ~0.5° grid cell containing the market, aggregated to calendar months. Months with less than 90% of days are flagged incomplete.</li>
          <li>Macro: IMF monthly consumer prices (all items and food) and the national exchange rate per US dollar.</li>
          <li>Agriculture: FAOSTAT annual national production, yield and harvested area for the crop related to the commodity.</li>
          <li>Context: World Bank annual development indicators, used descriptively and never interpolated to months.</li>
        </ul>
        <p>
          Extreme price moves are flagged with a robust z-score and classified, but never removed. A spike that is genuine
          is exactly what the spike model must learn to anticipate.
        </p>

        <h2 id="timing">What was known when</h2>
        <p>
          Every feature at forecast origin month <i>t</i> must have been publicly available by the end of <i>t</i>.
          ShockTrace distinguishes the period a value describes, its publication date, its retrieval date and the forecast
          information cut-off. Where a publication date is unknown, it applies a conservative release lag rather than
          assuming instant availability, and it never infers publication from the retrieval date.
        </p>
        <Example title="the information set for June 2020">
          <p>For an origin of June 2020, the model may use:</p>
          <ul className="list-disc pl-5">
            <li>Prices through June 2020 (lag 0).</li>
            <li>Weather through June 2020 (complete months only).</li>
            <li>IMF consumer prices through April 2020 (two-month release lag).</li>
            <li>The IMF exchange rate through May 2020 (one-month lag).</li>
            <li>FAOSTAT production for 2018 but not 2019: an annual value for year Y is treated as available only from December of Y+1.</li>
          </ul>
        </Example>
        <p>
          One limit remains: providers revise data, and ShockTrace sees today&rsquo;s vintage, not what was published at
          the time. The release lags reduce but do not remove this look-ahead.
        </p>

        <h2 id="targets">Forecast targets</h2>
        <p>For a price series <i>P</i> and origin <i>t</i>, two targets are fixed before any model is fitted:</p>
        <F>
          <i>y</i><sub>t</sub>(<i>h</i>) = ln <i>P</i><sub>t+h</sub> − ln <i>P</i><sub>t</sub>
          <span className="ml-6 text-base text-ink-3">log price change over horizon h = 1, 3 months</span>
        </F>
        <F>
          <i>s</i><sub>t</sub>(<i>h</i>) = 1[ <i>P</i><sub>t+h</sub> / <i>P</i><sub>t</sub> − 1 ≥ <i>c</i> ]
          <span className="ml-6 text-base text-ink-3">spike event, c = 10% by default</span>
        </F>
        <Example title="computing a target">
          <p>
            Maize costs 120 per kg in March and 133.20 in April. The one-month log change is ln(133.20 / 120) = ln(1.11) ≈
            0.104, and the rise of 11% exceeds the 10% threshold, so <i>s</i> = 1.
          </p>
          <p>
            If the June price is missing, the three-month target for March is <em>missing</em>. It is not recorded as
            &ldquo;no spike&rdquo;, which would silently bias the event rate downward.
          </p>
        </Example>
        <p>
          The 10% threshold is pre-specified. Results at 5%, 15% and 20% are reported as sensitivity analyses, never used to
          choose the headline.
        </p>

        <h2 id="features">Features</h2>
        <p>Features come in nested families, so each comparison adds exactly one kind of information:</p>
        <ul>
          <li><strong>A, price only:</strong> recent log changes (1, 3, 12 months), deviation from the 12-month mean, recent volatility, calendar month, and the average same-season change in the three previous years.</li>
          <li><strong>B, A plus weather:</strong> rainfall anomalies over 1, 3 and 6 months (and lagged), temperature and maximum-temperature anomalies, and counts of days at or above 35 °C.</li>
          <li><strong>C, B plus macro:</strong> consumer-price inflation, food inflation and exchange-rate depreciation, with release lags.</li>
          <li><strong>D, C plus agriculture:</strong> changes in national production, yield and harvested area.</li>
        </ul>
        <p>A weather anomaly is a standardised departure from the climatology of the same calendar month:</p>
        <F>
          <i>z</i><sub>t</sub> = (<i>x</i><sub>t</sub> − μ<sub>m</sub>) / σ<sub>m</sub>
        </F>
        <p>
          By default μ and σ are computed only from the same calendar month in <em>earlier years</em>, with at least ten
          years required. A fixed reference period is allowed only if it ends before the first test origin; otherwise the
          run stops with a leakage error.
        </p>
        <Example title="a rainfall anomaly">
          <p>
            March 2018 rainfall at a market&rsquo;s grid cell is 42 mm. Over the previous Marches (2008–2017) the mean is
            60 mm with a standard deviation of 12 mm. The anomaly is (42 − 60) / 12 = −1.5, a dry month. March 2018 itself
            plays no part in its own reference.
          </p>
        </Example>

        <h2 id="models">Models</h2>
        <p>
          Each family is fitted with the same model type so that the only difference between, say, A and B is the
          weather information:
        </p>
        <ul>
          <li>Baselines: no change (naive), seasonal naive, and the historical event rate for spikes.</li>
          <li>Ridge regression for price changes and L2-regularised logistic regression for spikes (primary models).</li>
          <li>Elastic net and gradient-boosted trees as specification checks.</li>
        </ul>
        <p>
          Every model is a pipeline of median imputation, standardisation and the estimator, fitted on training rows only.
          Regularisation strength is chosen on the last 24 months of each training window, with a purge gap so that no
          validation target was known when the inner training rows were fitted. For spikes, the alert threshold that
          maximises F1 is also chosen there, never on test data.
        </p>

        <h2 id="backtest">Rolling-origin backtest</h2>
        <p>
          The test period begins once 48 months of training origins exist. Models are refitted every 12 months on all rows
          whose <em>target</em> was observed by the refit date, then used for the next 12 origins without peeking.
        </p>
        <Example title="the first two folds of a three-month horizon">
          <p>
            Refit date January 2016: training origins run to October 2015, because the three-month target of an October
            2015 origin is January 2016, the last month observed. Test origins are January to December 2016.
          </p>
          <p>
            Refit date January 2017: training origins now run to October 2016, and the model predicts the 2017 origins.
            No row is ever scored by a model that saw its outcome.
          </p>
        </Example>

        <h2 id="metrics">Scoring</h2>
        <p>
          Price changes are scored with mean absolute error, root mean squared error, bias, error relative to the naive
          forecast, directional accuracy and the empirical coverage of 80% and 95% intervals. Spike probabilities are scored
          with the Brier score, Brier skill against the base rate, precision–recall AUC, precision, recall, F1, calibration
          by probability bin, and the confusion matrix.
        </p>
        <p>
          A metric is suppressed, not reported as zero, when there are fewer than 24 test origin months or fewer than 10
          spike events. Calibration bins with too few rows are hidden.
        </p>

        <h2 id="inference">Is the difference real?</h2>
        <p>
          Forecast errors for different markets in the same month are correlated, and multi-month targets overlap. So
          ShockTrace first averages the loss differential across series within each origin month,
        </p>
        <F>
          <i>d</i><sub>t</sub> = mean over series of [ <i>L</i>(A)<sub>it</sub> − <i>L</i>(B)<sub>it</sub> ]
        </F>
        <p>
          and then applies the Diebold–Mariano test with a Newey–West variance using max(<i>h</i> − 1, ⌊4(<i>T</i>/100)<sup>2/9</sup>⌋)
          lags and the Harvey–Leybourne–Newbold small-sample correction, compared against a <i>t</i> distribution. A 95%
          interval for the loss ratio B/A comes from a moving-block bootstrap over origin months, with block length
          max(<i>h</i>, <i>T</i><sup>1/3</sup>).
        </p>
        <Example title="the synthetic Demoland maize experiment">
          <p>
            For one-month price changes, the price-only ridge model had mean squared error 0.00459 and the weather-enhanced
            model 0.00348, a loss ratio of 0.76. Over 118 origin months with 4 HAC lags, the Diebold–Mariano statistic was
            2.67, one-sided p = 0.004, and the bootstrap interval for the ratio was 0.56 to 0.86. The loss differential
            favoured the weather model in both halves of the test period, so this comparison is &ldquo;improved&rdquo;.
          </p>
          <p>
            These numbers describe synthetic data built so that weather matters; they say nothing about any real market.
            The same run&rsquo;s one-month spike comparison was not significant, so the experiment as a whole is
            &ldquo;inconsistent&rdquo;.
          </p>
        </Example>

        <h2 id="verdicts">From tests to verdicts</h2>
        <p>Each primary comparison (B against A, for every task and horizon) gets one verdict:</p>
        <ul>
          <li><strong>Improved:</strong> B has lower loss, the one-sided test rejects at 5%, and the differential favours B in both halves of the test period.</li>
          <li><strong>Inconsistent:</strong> significant overall, but not in both halves.</li>
          <li><strong>Not improved:</strong> no significant difference, or B is significantly worse.</li>
          <li><strong>Insufficient evidence:</strong> too few test months or events to test.</li>
        </ul>
        <p>
          The experiment is &ldquo;improved&rdquo; only if every primary comparison with sufficient data is improved, and
          &ldquo;not improved&rdquo; only if none is improved or inconsistent. Anything in between is reported as
          inconsistent. Several primary comparisons are tested without a multiplicity correction, which is why the
          stability and sensitivity checks are shown alongside each verdict.
        </p>

        <h2 id="forecasts">Forward forecasts</h2>
        <p>
          After the backtest, the primary models are refitted on all available rows and produce a forecast from the latest
          origin. Intervals are empirical quantiles of the model&rsquo;s own out-of-sample residuals. Each forecast carries
          a validation status that says whether the model beat its baseline in the backtest, and a forecast is withheld
          when the latest price is more than two months old.
        </p>

        <h2 id="limits">What this does not show</h2>
        <ul>
          <li>Causation. All results are predictive comparisons.</li>
          <li>Production-area exposure. Weather is measured near the market, not where the crop was grown or imported from.</li>
          <li>Real-time performance. Inputs are a current data vintage with conservative lags.</li>
          <li>Generalisation. A result for one country and commodity says nothing about others.</li>
        </ul>
        <p>
          See the <Link href="/lab">Model laboratory</Link> for the full evidence behind any experiment, and{" "}
          <code>docs/RESEARCH_LIMITATIONS.md</code> for a longer discussion.
        </p>
      </article>
    </div>
  );
}
