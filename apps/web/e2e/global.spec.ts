import { expect, test } from "./fixtures";

import { API, noHorizontalScroll, selectByText, trackPageErrors, waitForContent } from "./helpers";

/**
 * Journeys over the global price inventory (95 countries) in a deployment that has the global price artefact installed.
 * Expectations come from the API's own discovery endpoints (checked against the Parquet files in the Python suite),
 * so the same spec runs against a local stack or production: set E2E_BASE_URL and E2E_API_URL.
 */

type Item = Record<string, string | number | boolean | null>;
const get = async (request: import("@playwright/test").APIRequestContext, path: string) => {
  const r = await request.get(`${API}${path}`);
  expect(r.status(), path).toBe(200);
  return r.json();
};
const firstSeries = async (request: import("@playwright/test").APIRequestContext, iso: string, extra = "") =>
  (await get(request, `/api/v1/global/countries/${iso}/series?limit=1&sort=observations${extra}`)).items[0] as Item;

test.describe("Global Market Explorer", () => {
  test("the inventory offers every country with stored prices and labels what each one is", async ({ page, request }) => {
    const errors = trackPageErrors(page);
    const inv = await get(request, "/api/v1/global/countries");
    await page.goto("/explorer");
    await waitForContent(page);
    const options = await page.locator("#f-country option").count();
    expect(options).toBe(inv.countries.length);
    expect(inv.countries.length).toBeGreaterThanOrEqual(10);
    // a country that is only ingested or validated must not be presented as research-eligible
    const plain = inv.countries.find((c: Item) => !c.research_eligible);
    if (plain) {
      await page.goto(`/explorer?country=${plain.country_iso3}`);
      await expect(page.getByTestId("country-summary")).toContainText(String(plain.name));
      await expect(page.getByTestId("country-summary")).not.toContainText("Forecast evaluated");
      await expect(page.getByTestId("country-summary")).toContainText("No forecast is shown");
    }
    expect(errors).toEqual([]);
  });

  for (const [iso, currency] of [
    ["ARM", "AMD"],
    ["TCD", "XAF"],
    ["NPL", "NPR"],
    ["ETH", "ETB"],
    ["HTI", "HTG"],
  ] as const) {
    test(`${iso}: country → commodity → series → history, completeness, provenance and export`, async ({ page, request }) => {
      const errors = trackPageErrors(page);
      const s = await firstSeries(request, iso);
      expect(s.currency).toBe(currency);
      await page.goto(`/explorer?country=${iso}`);
      await expect(page.locator("#f-country")).toHaveValue(iso);
      await selectByText(page, "#f-commodity", new RegExp(`^${String(s.commodity_name).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")} \\(`));
      const table = page.getByRole("region", { name: "Price series table" });
      await expect(table).toBeVisible();
      await expect(table).toContainText(currency);
      await page.goto(`/market?series=${s.series_id}`);
      await waitForContent(page);
      await expect(page.getByRole("heading", { level: 1 })).toContainText(String(s.commodity_name));
      await expect(page.getByText(`${currency} per ${s.unit}`).first()).toBeVisible();
      await expect(page.getByRole("img", { name: "Monthly price history" })).toBeVisible();
      await expect(page.getByTestId("data-tier")).toBeVisible();
      await expect(page.getByTestId("completeness")).toContainText("Months observed");
      await expect(page.getByText("Observation hash")).toBeVisible();

      // the observation table shows the first stored records, matching the API
      const obs = await get(request, `/api/v1/global/series/${s.series_id}/observations?limit=24`);
      await expect(page.getByTestId("observations-table").locator("tbody tr")).toHaveCount(obs.items.length);

      // the downloaded CSV contains every stored record, with currency and unit on every row
      const href = await page.getByRole("link", { name: "CSV" }).last().getAttribute("href");
      const res = await request.get(href!);
      expect(res.status()).toBe(200);
      const rows = (await res.text()).split("\n").filter((l) => l && !l.startsWith("# "));
      expect(rows.length - 1).toBe(obs.total);
      expect(rows[1]).toContain(currency);
      await noHorizontalScroll(page);
      expect(errors).toEqual([]);
    });
  }

  test("a commodity reported in more than one unit is split by unit and never combined", async ({ page, request }) => {
    let found: { iso: string; com: Item & { units: string[] } } | undefined;
    for (const iso of ["ETH", "HTI", "SYR", "NPL", "TCD"]) {
      const com = (await get(request, `/api/v1/global/countries/${iso}/commodities`)).items.find((c: { units: string[]; usable_series: number }) => c.units.length > 1 && c.usable_series > 1);
      if (com) {
        found = { iso, com };
        break;
      }
    }
    expect(found, "some country reports a commodity in two units").toBeTruthy();
    const { iso, com } = found!;
    await page.goto(`/explorer?country=${iso}&commodity=${com.commodity_code}`);
    await expect(page.locator("#f-unit")).toBeVisible();
    await page.locator("#f-unit").selectOption(com.units[0]);
    await expect(page).toHaveURL(/unit=/);
    const rows = page.getByRole("region", { name: "Price series table" }).locator("tbody tr");
    await expect(rows.first()).toBeVisible();
    for (const t of await rows.allTextContents()) expect(t).toContain(`/${com.units[0]}`);
    // two series of the same commodity in different units cannot be compared
    const a = await firstSeries(request, iso, `&commodity=${com.commodity_code}&unit=${encodeURIComponent(com.units[0])}&usable_only=false`);
    const b = await firstSeries(request, iso, `&commodity=${com.commodity_code}&unit=${encodeURIComponent(com.units[1])}&usable_only=false`);
    await page.goto(`/compare?s=${a.series_id},${b.series_id}`);
    await expect(page.getByTestId("not-comparable")).toContainText("cannot be compared");
  });

  test("short histories are hidden by default and flagged when shown; no forecast is claimed", async ({ page, request }) => {
    const all = await get(request, "/api/v1/global/countries/HTI/series?usable_only=false&limit=1");
    const usable = await get(request, "/api/v1/global/countries/HTI/series?limit=1");
    expect(all.total).toBeGreaterThan(usable.total);
    await page.goto("/explorer?country=HTI");
    await expect(page.getByText(`${usable.total.toLocaleString()} series match`)).toBeVisible();
    await page.getByLabel(/Include short histories/).click();
    await expect(page.getByLabel(/Include short histories/)).toBeChecked();
    await expect(page.getByText(`${all.total.toLocaleString()} series match`)).toBeVisible();
    const short = (await get(request, "/api/v1/global/countries/HTI/series?usable_only=false&sort=observations&limit=1&offset=" + (all.total - 1))).items[0] as Item;
    expect(short.usable).toBe(false);
    await page.goto(`/market?series=${short.series_id}`);
    await expect(page.getByTestId("completeness")).toContainText("Months observed");
    await expect(page.getByText(/Too short to describe/)).toBeVisible();
    await expect(page.getByRole("region", { name: "Forecast" }).getByText(/No evaluated forecasting model covers this series/)).toBeVisible();
  });

  test("a cross-country comparison is allowed only as indices, with prices never converted", async ({ page, request }) => {
    const countries = ["TCD", "NPL", "ARM", "ETH", "HTI", "SYR"];
    let pair: [Item, Item] | undefined;
    for (const name of ["Rice", "Sugar", "Wheat", "Maize", "Oil", "Lentils", "Beans"]) {
      const hits: Item[] = [];
      for (const iso of countries) {
        const items = (await get(request, `/api/v1/global/countries/${iso}/series?q=${name}&limit=100&sort=observations`)).items as Item[];
        hits.push(...items.map((i) => ({ ...i, iso })));
      }
      for (const x of hits) {
        const y = hits.find(
          (h) => h.country_iso3 !== x.country_iso3 && h.commodity_name === x.commodity_name && h.unit === x.unit && h.price_type === x.price_type && h.currency !== x.currency,
        );
        if (y) {
          pair = [x, y];
          break;
        }
      }
      if (pair) break;
    }
    expect(pair, "two countries report one commodity in the same unit").toBeTruthy();
    const [a, b] = pair!;
    await page.goto(`/compare?s=${a.series_id},${b.series_id}`);
    await waitForContent(page);
    await expect(page.getByRole("img", { name: "Indexed price movements by market" })).toBeVisible();
    await expect(page.getByRole("img", { name: "Price levels by market" })).toHaveCount(0);
    await expect(page.getByText(/currenc/i).first()).toBeVisible();
  });

  test("an unknown or unsupported country gives a clear message, not a crash @mobile", async ({ page }) => {
    const errors = trackPageErrors(page);
    await page.goto("/explorer?country=USA");
    await waitForContent(page);
    await expect(page.getByRole("alert").first()).toBeVisible();
    await noHorizontalScroll(page);
    expect(errors).toEqual([]);
  });

  test("the explorer fits a phone screen @mobile", async ({ page }) => {
    await page.goto("/explorer?country=ARM");
    await waitForContent(page);
    await expect(page.getByTestId("country-summary")).toBeVisible();
    await noHorizontalScroll(page);
  });
});

const EXAMPLE_PATH = "/investigate?series=ps_f0d5ea3ff6ef122d&event=2024-06&start=2022-06&end=2025-06";

test.describe("Price Shock Investigator (real data)", () => {
  test("the worked example reproduces: unusual, persistent and widespread, with no causal claim", async ({ page, request }) => {
    const errors = trackPageErrors(page);
    await page.goto("/investigate");
    await page.getByRole("link", { name: /Worked example/ }).click();
    await expect(page).toHaveURL(/series=ps_f0d5ea3ff6ef122d&event=2024-06/);
    await waitForContent(page);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Rice (imported) in Maradi Commune");
    const glance = page.getByRole("region", { name: "1. At a glance" });
    await expect(glance).toContainText("Widespread");
    await expect(glance).toContainText("+53.3%");
    await expect(glance).toContainText("no causal claim");
    // What the evidence can say about inflation and exchange rates depends on whether the economic-context
    // artefact is installed on the deployment under test; both states are asserted, never assumed.
    const ctx = await get(request, "/api/v1/context");
    const economic = page.getByRole("region", { name: "7. Economic context" });
    const evidence = page.getByRole("region", { name: "8. What the evidence supports" });
    if (ctx.available) {
      await expect(economic.getByTestId("economic-available")).toBeVisible();
      await expect(economic.getByTestId("economic-glance")).toContainText("+53.3%");
      await expect(economic.getByTestId("economic-glance")).toContainText("Consumer prices, all items");
      await expect(economic.getByTestId("economic-missing-food")).toContainText("published but empty"); // Niger: no food index
      await expect(economic).toContainText("What this context does not establish");
    } else {
      await expect(economic.getByTestId("economic-unavailable")).toBeVisible();
      await expect(evidence).toContainText("Cannot be assessed with the data integrated here");
    }
    expect(errors).toEqual([]);
  });

  test("the economic context reads well on a phone @mobile", async ({ page }) => {
    await page.goto(EXAMPLE_PATH);
    await waitForContent(page);
    await expect(page.getByRole("heading", { name: /^7\. Economic context/ })).toBeVisible();
    await expect(page.getByRole("region", { name: "7. Economic context" })).toBeVisible();
    await noHorizontalScroll(page);
  });

  test("discovery lists unusual rises across countries, food only by default @mobile", async ({ page, request }) => {
    const d = await get(request, "/api/v1/shocks?limit=5&sort=recent");
    expect(d.total).toBeGreaterThan(1000);
    await page.goto("/investigate");
    await waitForContent(page);
    await expect(page.getByRole("link", { name: /^Investigate / }).first()).toBeVisible();
    await noHorizontalScroll(page);
  });
});
