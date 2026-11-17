import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Methodology",
  description: "How ShockTrace measures unusual price movements, compares markets, builds weather features and evaluates forecasts, with formulas and limits.",
};

const SECTIONS = [
  ["data", "Data and units"],
  ["unusual", "Unusual movements"],
  ["compare", "Comparing markets"],
  ["timing", "What was known when"],
  ["targets", "Forecast targets"],
  ["features", "Features"],
  ["qc", "Weather quality control"],
  ["backtest", "Models and backtest"],
  ["inference", "Is a difference real?"],
  ["influence", "Does it depend on a few months?"],
  ["study", "The pre-registered study"],
  ["forecasts", "When a forecast is shown"],
  ["limits", "What this does not show"],
] as const;

function F({ children }: { children: React.ReactNode }) {
  return (
    <div className="formula" role="math">
      {children}
    </div>
  );
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
        <h1 className="font-serif text-4xl leading-tight text-ink md:text-5xl">Methodology</h1>
        <p className="mt-4 text-xl">
          The rules behind every number on this site: how movements are judged unusual, when markets may be compared, what a forecast was allowed to know, and how models are
          scored. The full write-up is in <code>docs/METHODOLOGY.md</code>; the study protocol is in <code>docs/research/RESEARCH_PROTOCOL.md</code>.
        </p>

        <h2 id="data">Data and units</h2>
        <p>
          Prices are monthly market reports collected by the World Food Programme and partners, obtained through HDX HAPI. A <em>series</em> is one market, commodity, unit,
          price type and currency; series that differ in any of these are never merged. Each price carries the month it describes. That month is not the date the price was
          published, which the source does not provide.
        </p>
        <p>
          Months with no valid observation stay empty. Nothing is interpolated, and conflicting duplicate records are excluded and counted. Weather is NASA POWER daily data on a
          0.5° × 0.625° grid, aggregated to months only when at least 90% of days are present.
        </p>

        <h2 id="unusual">Unusual movements</h2>
        <p>For one series, the change ending in month T over k months is</p>
        <F>
          r<sub>T</sub>(k) = ln P<sub>T</sub> − ln P<sub>T−k</sub>
        </F>
        <p>
          with k = 1 when the previous month was observed, and otherwise the distance to the last observed month. It is compared only with earlier changes of the same span in
          the same series. Two statistics are reported: the share of earlier changes that were smaller in absolute size, and a robust z-score
        </p>
        <F>
          z = (r<sub>T</sub> − median) / (1.4826 × MAD)
        </F>
        <p>
          The label follows the first: below 80% typical, 80–95% larger than usual, 95–99% unusual, 99% or more exceptional. At least 24 earlier changes are required, and fewer
          than 48 is marked as a short history. A second comparison uses only changes that ended in the same calendar month.
        </p>
        <Example title="a one-month rise">
          <p>A series has 30 earlier monthly changes, alternating +1% and −1%, and then rises 10%.</p>
          <p>
            All 30 earlier changes are smaller in size, so the percentile is 100%. The median is 0 and the MAD is 0.01, so z = 0.10 / (1.4826 × 0.01) = 6.7. The label is
            &ldquo;exceptional&rdquo;, marked as a short history because there are fewer than 48 reference changes.
          </p>
        </Example>
        <p>
          The page also reports how many other markets for the same commodity and country moved the same way that month. A movement that no other market shared and that reversed
          the next month can be a reporting anomaly. None of these labels is a finding of a shortage or a crisis, and none says why a price moved.
        </p>

        <h2 id="compare">Comparing markets</h2>
        <p>
          Price levels are compared only between series with the same commodity, price type, unit and currency. Series in different currencies are compared only as indices, each
          divided by its own value in the first month when all selected series were observed:
        </p>
        <F>
          I<sub>t</sub> = 100 × P<sub>t</sub> / P<sub>base</sub>
        </F>
        <p>
          An index compares movements. It does not compare living costs, and ShockTrace applies no currency conversion: it holds no verified, date-matched exchange rates for
          every pair, and a nominal conversion would not make prices comparable in purchasing-power terms. Series that differ in commodity, unit or price type are refused.
        </p>

        <h2 id="timing">What was known when</h2>
        <p>
          A forecast made at the end of month <i>t</i> may use only information available then. The price sources do not publish release dates, and the newest WFP month typically
          appears one to two months late. ShockTrace therefore states an explicit assumption, the price release lag L, and evaluates three scenarios: L = 0, 1 and 2 months. At
          origin <i>t</i> the last price a model may use is P<sub>t−L</sub>. Weather is used through the complete month <i>t</i>.
        </p>
        <p>
          These are assumed scenarios, and the data are today&rsquo;s vintage (later revisions are included). The evaluations are retrospective backtests under stated lag
          assumptions. They are not verified point-in-time forecasts.
        </p>

        <h2 id="targets">Forecast targets</h2>
        <F>
          y<sub>t</sub>(h) = ln P<sub>t+h</sub> − ln P<sub>t−L</sub>
        </F>
        <p>
          The change is measured from the last price assumed published, so no target depends on a reference price the forecaster could not have seen. The spike event is
          P<sub>t+h</sub> / P<sub>t−L</sub> − 1 ≥ 10%. If either price is missing, the target is missing.
        </p>
        <Example title="origin March, one month ahead, lag 1">
          <p>Prices: January 100, February 110, March 121, April 133.1.</p>
          <p>
            With L = 1 the last published price at the end of March is February&rsquo;s. The target is ln 133.1 − ln 110 = 0.191, a 21% rise over two months, and the features may
            use prices up to February only. With L = 0 the target would be ln 133.1 − ln 121 = 0.095.
          </p>
        </Example>
        <p>
          A model is trained at a refit date <i>c</i> only on rows whose target price was already published: origin + h + L ≤ c. Tests alter every later price and check that
          features and training sets do not change.
        </p>

        <h2 id="features">Features</h2>
        <h3>A: price history</h3>
        <p>
          Log changes over 1, 3 and 12 months, the previous month&rsquo;s change, deviation from the 12-month mean, six-month volatility, calendar terms, and the average change
          over the same span in the three previous years. All use prices up to <i>t</i>−L.
        </p>
        <h3>B: weather near the market</h3>
        <p>Nine anomaly features from the grid cell containing the market. An anomaly compares a month with the same calendar month in earlier years only:</p>
        <F>
          z<sub>t</sub> = (x<sub>t</sub> − μ<sub>m, earlier years</sub>) / σ<sub>m, earlier years</sub>, clipped to ±4
        </F>
        <h3>P: weather where the crop is grown</h3>
        <p>Grid cells are weighted by the crop&rsquo;s harvested area from IFPRI MapSPAM 2010:</p>
        <F>
          W(c, t) = Σ<sub>i</sub> w(c, i) × X(i, t), &nbsp; w ≥ 0, &nbsp; Σ<sub>i</sub> w(c, i) = 1
        </F>
        <p>
          The crop calendar (World Bank / JRC) gives the growing season. Rainfall and heat days are accumulated over the season to date and compared with the same stage of earlier
          seasons, so an unfinished season is never compared with completed ones. Six features result: season-to-date rainfall anomaly, the previous season&rsquo;s anomaly,
          season heat anomaly, onset rainfall anomaly, an in-season indicator and months since harvest.
        </p>
        <p>
          The weights show where a crop was grown around 2010 across the country. They do not identify the farms that supply a given market, and they ignore imports and stocks.
        </p>

        <h2 id="qc">Weather quality control</h2>
        <p>
          NASA POWER reports 276.5 mm of rain on 2 December 2025 for a cell in south-west Burkina Faso, in the dry season, with similar values in eight neighbouring cells. The
          IMERG satellite product reports 1.6 mm for that day and CHIRPS under 4 mm. Because neighbours agree with each other, a spatial check cannot catch this. The screen is
          climatological and per cell.
        </p>
        <p>
          A daily value is flagged when it is at least 50 mm and more than twice the largest unflagged value the same cell recorded in the surrounding three calendar months of
          earlier years. Flagged days are treated as missing. The raw monthly total is kept beside the screened one, the flag count is stored, and experiments can be re-run on raw
          data. The screen will also flag a genuine record-breaking storm, which is why raw values are never deleted.
        </p>

        <h2 id="backtest">Models and backtest</h2>
        <p>
          Ridge regression for price changes and L2-regularised logistic regression for spikes, with median imputation and scaling fitted inside each training window. The
          penalty is chosen on a later slice of the training window. Models are refitted every 12 months on an expanding window and scored on the following year. Benchmarks are
          the no-change forecast, the seasonal naive forecast and the historical spike rate. Models in a comparison are scored on exactly the same rows.
        </p>

        <h2 id="inference">Is a difference real?</h2>
        <p>
          Forecast errors in the same month are correlated across markets, and multi-month forecasts overlap. Loss differences are therefore averaged across markets within each
          month, and the resulting monthly series is tested with the Diebold–Mariano statistic using a Newey–West variance and the Harvey–Leybourne–Newbold correction. The
          effective sample is the number of months, about 65, not the thousands of individual forecasts.
        </p>
        <p>
          Intervals come from a moving-block bootstrap over months of the ratio of monthly mean losses, the same quantity the test examines. Families of pre-specified tests are
          adjusted with Holm&rsquo;s procedure.
        </p>

        <h2 id="influence">Does it depend on a few months?</h2>
        <p>
          Each comparison reports the loss ratio after leaving out each month, each market and each weather cell, the ratio without the three most influential months, and the
          ratio without rows whose weather was quality-flagged. A comparison is marked as depending on few observations when any of these moves the ratio by more than 0.02 and
          more than half of the apparent effect. Nothing is removed from the primary result.
        </p>

        <h2 id="study">The pre-registered study</h2>
        <p>
          Burkina Faso&rsquo;s test period was examined while the method was being developed, so its results are exploratory. The confirmatory test uses Mali and Niger, on which
          no model had been run when the protocol was frozen and tagged in the repository. Eight tests were fixed in advance: two countries, two horizons, and the
          production-region model against price history and against market-local weather, pooled over each country&rsquo;s crops.
        </p>
        <p>
          An improvement counts as established only if it survives the Holm adjustment, favours the weather model in both halves of the test period, beats a placebo built from
          weather five years earlier, and does not depend on a few observations. A result that is not significant is reported as no established improvement. It is not evidence
          that weather has no effect. Results are in the <Link href="/lab">Research Lab</Link>.
        </p>

        <h2 id="forecasts">When a forecast is shown</h2>
        <p>
          A forecast appears only for a series covered by a current out-of-sample evaluation with at least 24 test months. It is labelled as having beaten its benchmark or as
          having no demonstrated skill, and it states its origin, the last price it used and its target month. Intervals are empirical quantiles of past out-of-sample errors.
          Series that are stale or too short have their forecast withheld, with the reason.
        </p>

        <h2 id="limits">What this does not show</h2>
        <ul>
          <li>Causes. Prices respond to transport, trade policy, conflict, currency, storage and demand as well as weather. Nothing here separates them.</li>
          <li>Real-time performance. Timing rests on assumed publication lags and today&rsquo;s data vintage.</li>
          <li>Supply origins. Neither market-cell nor production-region weather identifies where a market&rsquo;s supply comes from.</li>
          <li>Small effects. With about 65 monthly observations, improvements of a few percent in forecast loss cannot be detected.</li>
          <li>Other places. The study covers three Sahelian countries and four staples.</li>
        </ul>
      </article>
    </div>
  );
}
