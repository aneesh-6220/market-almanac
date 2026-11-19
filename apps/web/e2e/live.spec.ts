import { expect, test } from "./fixtures";

import { API, noHorizontalScroll, selectByText, trackPageErrors, waitForContent } from "./helpers";

/**
 * Journeys over real, ingested WFP / NASA POWER data and the stored study results.
 * Needs the live public data bundle (snapshot 20261116T232023_aee95f for Mali prices).
 * Expected values below are taken from the stored artefacts, not from the UI.
 */
const MILLET_ANSONGO = "ps_0ea6a8b827d55559"; // Mali, Gao, Ansongo, millet, retail, XOF/KG
const MILLET_BADALABOUGOU = "ps_59dd8957cb1cb5d7"; // Mali, Bamako, Badalabougou, millet, retail, XOF/KG

test.describe("Market Almanac (live data)", () => {
  test("home shows real coverage and the pre-registered study outcome", async ({ page }) => {
    const errors = trackPageErrors(page);
    await page.goto("/");
    await expect(page.getByTestId("synthetic-band")).toHaveCount(0);
    await expect(page.getByTestId("home-coverage")).toContainText("Mali");
    const study = page.getByTestId("study-summary");
    await expect(study).toContainText("No established improvement");
    await expect(study).toContainText("1.169"); // MLI P vs A, h=1: results_confirmatory.json
    expect(errors).toEqual([]);
  });

  test("explore Mali millet and open a real market", async ({ page }) => {
    await page.goto("/explorer?country=MLI");
    await expect(page.locator("#f-country")).toHaveValue("MLI");
    await selectByText(page, "#f-commodity", /^Millet \(/);
    await selectByText(page, "#f-market", /^Ansongo/);
    await page.getByRole("region", { name: "Price series table" }).getByRole("link", { name: /Millet/ }).first().click();
    await expect(page).toHaveURL(new RegExp(`series=${MILLET_ANSONGO}`));
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Millet in Ansongo");
  });

  test("market page shows the latest observation with month, unit and provenance", async ({ page, request }) => {
    const hist = await (await request.get(`${API}/api/v1/series/${MILLET_ANSONGO}/history`)).json();
    const last = hist.items.filter((d: { price: number | null }) => d.price !== null).at(-1);
    await page.goto(`/market?series=${MILLET_ANSONGO}`);
    await expect(page.getByText("XOF per KG").first()).toBeVisible();
    const brief = page.getByTestId("market-brief");
    await expect(brief).toContainText(`${last.price} XOF per KG`);
    await expect(page.getByText("Snapshot").first()).toBeVisible();
    await expect(page.getByRole("img", { name: "Monthly price history" })).toBeVisible();
  });

  test("compare two Mali millet markets in levels; refuse mismatched units", async ({ page, request }) => {
    await page.goto(`/compare?s=${MILLET_ANSONGO},${MILLET_BADALABOUGOU}&view=price`);
    await expect(page.getByText("Levels and movements comparable")).toBeVisible();
    await expect(page.getByRole("img", { name: "Price levels by market" })).toBeVisible();
    const nga = await (await request.get(`${API}/api/v1/catalog/series?country=NGA&q=millet&limit=1`)).json();
    await page.goto(`/compare?s=${MILLET_ANSONGO},${nga.items[0].series_id}`);
    await expect(page.getByTestId("not-comparable")).toContainText("cannot be compared");
  });

  test("research lab shows current study results; superseded runs are not listed", async ({ page, request }) => {
    await page.goto("/lab");
    await expect(page.getByText("No established improvement").first()).toBeVisible();
    const exps = await (await request.get(`${API}/api/v1/experiments`)).json();
    const ids = (Array.isArray(exps) ? exps : exps.items).map((e: { id: string }) => e.id);
    expect(ids.length).toBeGreaterThan(0);
    expect(ids.filter((id: string) => id.startsWith("exp_2026"))).toEqual([]);
    const old = await request.get(`${API}/api/v1/experiments/exp_20261116234216_a5e201`);
    expect([200, 404]).toContain(old.status()); // retrievable by id when its artefacts are installed, never listed
  });

  test("forecast explorer qualifies forecasts against the no-change benchmark", async ({ page }) => {
    await page.goto("/forecasts");
    await expect(page.getByTestId("naive-benchmark").first()).toBeVisible();
    await expect(page.getByText("Forecast origin")).toBeVisible();
  });

  test("live pages fit a phone screen @mobile", async ({ page }) => {
    for (const path of ["/", "/explorer?country=MLI", `/market?series=${MILLET_ANSONGO}`, `/compare?s=${MILLET_ANSONGO},${MILLET_BADALABOUGOU}`, "/lab", "/data"]) {
      await page.goto(path);
      await waitForContent(page);
      await noHorizontalScroll(page);
    }
  });
});
