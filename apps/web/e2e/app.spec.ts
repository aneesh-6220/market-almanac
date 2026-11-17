import { expect, test } from "@playwright/test";

test.describe("ShockTrace demo", () => {
  test("home states the question, labels synthetic data and shows the latest verdict", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("weather");
    await expect(page.getByText("Demo mode.")).toBeVisible();
    const evidence = page.getByTestId("home-evidence");
    await expect(evidence.getByText("synthetic", { exact: true }).first()).toBeVisible();
    await expect(evidence.getByRole("figure", { name: /forest plot/i })).toBeVisible();
  });

  test("explorer: choose a market and see its price history", async ({ page }) => {
    await page.goto("/explorer");
    await expect(page.getByLabel("Country")).toHaveValue("XDM");
    const market = page.locator("#f-market");
    await expect(market.locator("option")).not.toHaveCount(1);
    const firstMarket = await market.locator("option").nth(1).getAttribute("value");
    await market.selectOption(firstMarket!);
    await expect(page).toHaveURL(/market=/);
    await expect(page.getByRole("img", { name: "Monthly price history" })).toBeVisible();
  });

  test("market analysis shows prices, weather and quality context", async ({ page }) => {
    await page.goto("/data");
    await page.getByRole("link", { name: "Highmoor" }).first().click();
    await expect(page).toHaveURL(/\/market\?series=ps_/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Highmoor");
    await expect(page.getByRole("img", { name: "Monthly price history" })).toBeVisible();
    await expect(page.getByRole("img", { name: /rainfall and temperature anomalies/i })).toBeVisible();
    await expect(page.getByText("Observed months")).toBeVisible();
    await expect(page.getByText("Forecasting", { exact: true })).toBeVisible();
  });

  test("forecast explorer shows a forecast with its validation status", async ({ page }) => {
    await page.goto("/forecasts?experiment=demo_1_dm-maize");
    await expect(page.getByRole("heading", { name: /Maize \(white\) in/ })).toBeVisible();
    await expect(page.getByText(/Beat its baseline out of sample|No better than its baseline|Too little validation/).first()).toBeVisible();
    await expect(page.getByText(/80%: .* 95%: /).first()).toBeVisible();
    await expect(page.getByRole("img", { name: /forecast and prediction intervals/ })).toBeVisible();
  });

  test("model lab compares models and offers downloads", async ({ page }) => {
    await page.goto("/lab?experiment=demo_1_dm-maize");
    await expect(page.getByText("Results were inconsistent.")).toBeVisible();
    await page.getByRole("tab", { name: "Other model types" }).click();
    await expect(page.getByRole("tab", { name: "Other model types" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByText(/Boosting \(B\)/).first()).toBeVisible();
    const bundle = page.getByRole("link", { name: "Download bundle" });
    await expect(bundle).toHaveAttribute("href", /\/api\/v1\/exports\/demo_1_dm-maize\?format=zip/);
    const res = await page.request.get((await bundle.getAttribute("href"))!);
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toContain("zip");
  });

  test("data page shows provenance for every source", async ({ page }) => {
    await page.goto("/data");
    for (const name of ["HDX HAPI", "NASA POWER", "World Bank", "IMF", "FAOSTAT"]) {
      await expect(page.getByRole("article", { name: new RegExp(name) })).toBeVisible();
    }
    await expect(page.getByText("Every series and why it is or is not eligible")).toBeVisible();
  });

  test("methodology explains timing rules with worked examples", async ({ page }) => {
    await page.goto("/methodology");
    await expect(page.getByRole("heading", { name: "What was known when" })).toBeVisible();
    await expect(page.getByLabel(/Worked example: the information set/)).toContainText("April 2020");
  });

  test("navigation works on a phone-sized screen @mobile", async ({ page }) => {
    const noHorizontalScroll = async () => {
      const [sw, w] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
      expect(sw).toBeLessThanOrEqual(w + 1);
    };
    for (const path of ["/lab?experiment=demo_1_dm-maize", "/forecasts?experiment=demo_1_dm-maize", "/data", "/methodology"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await noHorizontalScroll();
    }
    await page.goto("/");
    await expect(page.getByTestId("home-evidence").getByRole("figure", { name: /forest plot/i })).toBeVisible();
    await noHorizontalScroll();
    await page.getByRole("button", { name: /menu/i }).click();
    await page.locator("#mobile-nav").getByRole("link", { name: "Model lab", exact: true }).click();
    await expect(page).toHaveURL(/\/lab/);
  });
});
