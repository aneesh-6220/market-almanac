import { expect, test } from "@playwright/test";

import { API, noHorizontalScroll, trackPageErrors, waitForContent } from "./helpers";

test.describe("ShockTrace (synthetic demo)", () => {
  test("home explains the product and labels synthetic data", async ({ page }) => {
    const errors = trackPageErrors(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("food prices");
    await expect(page.getByTestId("synthetic-band")).toContainText("synthetic");
    await expect(page.getByTestId("home-coverage")).toContainText("Demoland");
    expect(errors).toEqual([]);
  });

  test("explore: choose a commodity and a market, then open its history", async ({ page }) => {
    await page.goto("/explorer");
    const commodity = page.locator("#f-commodity");
    await expect(commodity.locator("option")).not.toHaveCount(1);
    await commodity.selectOption({ index: 1 });
    await expect(page).toHaveURL(/commodity=/);
    const table = page.getByRole("region", { name: "Price series table" });
    await table.getByRole("link").first().click();
    await expect(page).toHaveURL(/\/market\?series=ps_[0-9a-f]{16}/);
    await expect(page.getByRole("img", { name: "Monthly price history" })).toBeVisible();
    await expect(page.getByTestId("market-brief")).toContainText("observed for");
  });

  test("market history CSV export downloads observed prices", async ({ page, request }) => {
    const list = await (await request.get(`${API}/api/v1/catalog/series?limit=1`)).json();
    const sid = list.items[0].series_id as string;
    await page.goto(`/market?series=${sid}`);
    const href = await page.getByRole("link", { name: "CSV" }).getAttribute("href");
    const res = await request.get(href!);
    expect(res.status()).toBe(200);
    const lines = (await res.text()).trim().split("\n");
    expect(lines.some((l) => /period/.test(l))).toBe(true);
    expect(lines.length).toBeGreaterThan(12);
  });

  test("compare: two markets of the same commodity, shareable and exportable", async ({ page, request }) => {
    const list = await (await request.get(`${API}/api/v1/catalog/series?limit=200`)).json();
    const items = list.items as { series_id: string; commodity_name: string; unit: string; price_type: string }[];
    const a = items[0];
    const b = items.find(
      (x) => x.series_id !== a.series_id && x.commodity_name === a.commodity_name && x.unit === a.unit && x.price_type === a.price_type,
    )!;
    await page.goto(`/compare?s=${a.series_id},${b.series_id}`);
    await expect(page.getByRole("img", { name: /Indexed price movements by market|Price levels by market/ })).toBeVisible();
    await expect(page.getByRole("region", { name: "Comparison statistics" })).toBeVisible();
    await page.reload(); // the selection is restored from the URL alone
    await expect(page.getByRole("button", { name: /^Remove / })).toHaveCount(2);
    const csv = await request.get(`${API}/api/v1/compare?series_id=${a.series_id}&series_id=${b.series_id}&format=csv`);
    expect(csv.status()).toBe(200);
  });

  test("research lab and forecast explorer load experiment evidence", async ({ page }) => {
    await page.goto("/lab");
    await expect(page.getByRole("region", { name: "Conclusion" })).toBeVisible();
    await page.goto("/forecasts");
    await expect(page.getByText(/Beat its baseline out of sample|No better than its baseline|Too little validation/).first()).toBeVisible();
    await expect(page.getByTestId("naive-benchmark").first()).toBeVisible();
  });

  test("data page shows provenance for every source", async ({ page }) => {
    await page.goto("/data");
    for (const name of ["HDX HAPI", "NASA POWER", "World Bank", "IMF", "FAOSTAT"]) {
      await expect(page.getByRole("article", { name: new RegExp(name) })).toBeVisible();
    }
  });

  test("an unreachable API produces an intelligible message, not a crash", async ({ page }) => {
    const errors = trackPageErrors(page);
    await page.route(`${API}/**`, (route) => route.abort());
    await page.goto("/explorer");
    await expect(page.getByRole("alert").first()).toContainText("Could not load");
    expect(errors).toEqual([]);
  });

  test("navigation and layout work on a phone-sized screen @mobile", async ({ page }) => {
    for (const path of ["/", "/explorer", "/compare", "/lab", "/forecasts", "/data", "/methodology"]) {
      await page.goto(path);
      await waitForContent(page);
      await noHorizontalScroll(page);
    }
    await page.goto("/");
    await page.getByRole("button", { name: /menu/i }).click();
    await page.locator("#mobile-nav").getByRole("link", { name: "Research Lab", exact: true }).click();
    await expect(page).toHaveURL(/\/lab/);
  });
});
