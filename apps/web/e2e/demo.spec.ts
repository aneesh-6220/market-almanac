import { expect, test } from "@playwright/test";

import {
  API,
  noHorizontalScroll,
  trackPageErrors,
  waitForContent,
} from "./helpers";

test.describe("Market Almanac (synthetic demo)", () => {
  test("home explains the product and labels synthetic data", async ({
    page,
  }) => {
    const errors = trackPageErrors(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText(
      "food prices",
    );
    await expect(page.getByTestId("synthetic-band")).toContainText("synthetic");
    await expect(page.getByTestId("home-coverage")).toContainText("Demoland");
    expect(errors).toEqual([]);
  });

  test("explore: choose a commodity and a market, then open its history", async ({
    page,
  }) => {
    await page.goto("/explorer");
    const commodity = page.locator("#f-commodity");
    await expect(commodity.locator("option")).not.toHaveCount(1);
    await commodity.selectOption({ index: 1 });
    await expect(page).toHaveURL(/commodity=/);
    const table = page.getByRole("region", { name: "Price series table" });
    await table.getByRole("link").first().click();
    await expect(page).toHaveURL(/\/market\?series=ps_[0-9a-f]{16}/);
    await expect(
      page.getByRole("img", { name: "Monthly price history" }),
    ).toBeVisible();
    await expect(page.getByTestId("market-brief")).toContainText(
      "observed for",
    );
  });

  test("market history CSV export downloads observed prices", async ({
    page,
    request,
  }) => {
    const list = await (
      await request.get(`${API}/api/v1/catalog/series?limit=1`)
    ).json();
    const sid = list.items[0].series_id as string;
    await page.goto(`/market?series=${sid}`);
    // the price-history export is the first CSV link; the observations panel has its own
    const href = await page
      .getByRole("link", { name: "CSV" })
      .first()
      .getAttribute("href");
    const res = await request.get(href!);
    expect(res.status()).toBe(200);
    const lines = (await res.text()).trim().split("\n");
    expect(lines.some((l) => /period/.test(l))).toBe(true);
    expect(lines.length).toBeGreaterThan(12);
  });

  test("compare: two markets of the same commodity, shareable and exportable", async ({
    page,
    request,
  }) => {
    const list = await (
      await request.get(`${API}/api/v1/catalog/series?limit=200`)
    ).json();
    const items = list.items as {
      series_id: string;
      commodity_name: string;
      unit: string;
      price_type: string;
    }[];
    const a = items[0];
    const b = items.find(
      (x) =>
        x.series_id !== a.series_id &&
        x.commodity_name === a.commodity_name &&
        x.unit === a.unit &&
        x.price_type === a.price_type,
    )!;
    await page.goto(`/compare?s=${a.series_id},${b.series_id}`);
    await expect(
      page.getByRole("img", {
        name: /Indexed price movements by market|Price levels by market/,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Comparison statistics" }),
    ).toBeVisible();
    await page.reload(); // the selection is restored from the URL alone
    await expect(page.getByRole("button", { name: /^Remove / })).toHaveCount(2);
    const csv = await request.get(
      `${API}/api/v1/compare?series_id=${a.series_id}&series_id=${b.series_id}&format=csv`,
    );
    expect(csv.status()).toBe(200);
  });

  test("research lab and forecast explorer load experiment evidence", async ({
    page,
  }) => {
    await page.goto("/lab");
    await expect(
      page.getByRole("region", { name: "Conclusion" }),
    ).toBeVisible();
    await page.goto("/forecasts");
    await expect(
      page
        .getByText(
          /Beat its baseline out of sample|No better than its baseline|Too little validation/,
        )
        .first(),
    ).toBeVisible();
    await expect(page.getByTestId("naive-benchmark").first()).toBeVisible();
  });

  test("data page shows provenance for every source", async ({ page }) => {
    await page.goto("/data");
    for (const name of [
      "HDX HAPI",
      "NASA POWER",
      "World Bank",
      "IMF",
      "FAOSTAT",
    ]) {
      await expect(
        page.getByRole("article", { name: new RegExp(name) }),
      ).toBeVisible();
    }
  });

  test("an unreachable API produces an intelligible message, not a crash", async ({
    page,
  }) => {
    const errors = trackPageErrors(page);
    // A virtual clock lets the retry back-off (about 35 s in real time) run instantly.
    await page.clock.install();
    await page.route(`${API}/**`, (route) => route.abort());
    await page.goto("/explorer");
    // while the service looks temporarily unreachable the page says it is retrying, rather than failing at once
    await expect(page.getByRole("status").filter({ hasText: "retrying" }).first()).toBeVisible();
    // each retry needs real network time between timer ticks, so advance the clock in steps until it gives up
    await expect(async () => {
      await page.clock.runFor(11_000);
      await expect(page.getByRole("alert").filter({ hasText: "Could not load" }).first()).toBeVisible({ timeout: 300 });
    }).toPass({ timeout: 30_000 });
    expect(errors).toEqual([]);
  });

  test("a busy server (503 with Retry-After) is retried and the page then loads", async ({
    page,
  }) => {
    const errors = trackPageErrors(page);
    await page.clock.install();
    let busyFor = 2;
    await page.route(`${API}/api/v1/global/countries`, (route) => {
      if (busyFor-- > 0) {
        return route.fulfill({
          status: 503,
          headers: {
            "content-type": "application/json",
            "retry-after": "5",
            "access-control-allow-origin": "*",
            "access-control-expose-headers": "retry-after",
          },
          body: JSON.stringify({ error: "busy", detail: "The server is busy with other requests; retry shortly." }),
        });
      }
      return route.continue();
    });
    await page.goto("/explorer");
    await expect(page.getByRole("status").filter({ hasText: "retrying" }).first()).toBeVisible();
    await expect(async () => {
      await page.clock.runFor(6_000);
      expect(busyFor).toBeLessThan(0); // both 503s were served, and then the real answer was requested
      await expect(page.getByRole("status").filter({ hasText: "Loading countries" })).toHaveCount(0, { timeout: 300 });
    }).toPass({ timeout: 30_000 });
    await expect(page.locator("#f-country option").first()).toBeAttached();
    await expect(page.getByRole("alert").filter({ hasText: /./ })).toHaveCount(0); // the Next route announcer is an empty alert
    expect(errors).toEqual([]);
  });

  test("research workbench validates a specification without running it", async ({
    page,
  }) => {
    const errors = trackPageErrors(page);
    await page.goto("/workbench");
    await page.getByRole("button", { name: "Validate" }).click();
    await expect(page.getByText("valid", { exact: true })).toBeVisible();
    await expect(
      page.getByText(/research run my-study-v1\.yaml/),
    ).toBeVisible();
    await page.getByLabel("Specification YAML").fill("id: x");
    await page.getByRole("button", { name: "Validate" }).click();
    await expect(page.getByText(/problems?$/).first()).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("global pages give honest states when no registry or study is published", async ({
    page,
  }) => {
    const errors = trackPageErrors(page);
    for (const path of ["/atlas", "/studies", "/forecastability"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    }
    await page.goto("/studies");
    await expect(
      page.getByRole("link", { name: /Sahel production weather v1/ }),
    ).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("investigate: discover an unusual rise, open it, reproduce it and export its brief", async ({
    page,
    request,
  }) => {
    const errors = trackPageErrors(page);
    await page.goto("/investigate");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Price shock investigator");
    const open = page.getByRole("link", { name: /^Investigate / }).first();
    await expect(open).toBeVisible();
    await open.click();
    await expect(page).toHaveURL(/\/investigate\?series=ps_[0-9a-f]{16}&event=\d{4}-\d{2}/);
    await waitForContent(page);
    for (const n of ["1. At a glance", "2. Price history", "3. Compared with", "4. Comparable markets", "5. Other foods", "6. Context", "7. What the evidence", "8. Method"]) {
      await expect(page.getByRole("heading", { name: new RegExp(`^${n.replace(".", "\\.")}`) })).toBeVisible();
    }
    await expect(page.getByRole("img", { name: /Monthly .* price in/ })).toBeVisible();
    // the brief carries the configuration that reproduces it
    const md = await page.getByRole("link", { name: /Research brief/ }).getAttribute("href");
    const brief = await (await request.get(md!)).text();
    const configId = /Configuration:\*\* `([0-9a-f]{16})`/.exec(brief)?.[1];
    expect(configId).toBeTruthy();
    await expect(page.getByText(configId!, { exact: true })).toBeVisible();
    // the permalink (event and window in the URL) reproduces the same configuration
    const url = new URL(page.url());
    const sid = url.searchParams.get("series")!;
    const doc = await (await request.get(`${API}/api/v1/investigations/${sid}?event=${url.searchParams.get("event")}`)).json();
    await page.goto(`/investigate?series=${sid}&event=${doc.config.event}&start=${doc.config.window.start}&end=${doc.config.window.end}`);
    await waitForContent(page);
    await expect(page.getByText(doc.config_id, { exact: true })).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("investigate: an investigation reads well on a phone @mobile", async ({ page, request }) => {
    const page1 = await (await request.get(`${API}/api/v1/shocks?limit=1`)).json();
    await page.goto(`/investigate?series=${page1.items[0].series_id}&event=${page1.items[0].peak}`);
    await waitForContent(page);
    await expect(page.getByRole("heading", { name: /^1\. At a glance/ })).toBeVisible();
    await noHorizontalScroll(page);
  });

  test("navigation and layout work on a phone-sized screen @mobile", async ({
    page,
  }) => {
    for (const path of [
      "/",
      "/explorer",
      "/compare",
      "/lab",
      "/forecasts",
      "/data",
      "/methodology",
      "/workbench",
      "/studies",
      "/investigate",
    ]) {
      await page.goto(path);
      await waitForContent(page);
      await noHorizontalScroll(page);
    }
    await page.goto("/");
    await page.getByRole("button", { name: /menu/i }).click();
    await page
      .locator("#mobile-nav")
      .getByRole("link", { name: "Research Lab", exact: true })
      .click();
    await expect(page).toHaveURL(/\/lab/);
  });
});
