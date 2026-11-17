import { expect, type Page } from "@playwright/test";

export const API = process.env.E2E_API_URL ?? "http://localhost:8000";

export async function noHorizontalScroll(page: Page) {
  const [sw, w] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
  expect(sw).toBeLessThanOrEqual(w + 1);
}

/** Collect uncaught page errors (expected API 404s are not page errors). */
export function trackPageErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

/** Select the first option of a <select> whose visible text matches ``pattern`` (waits for options to load). */
export async function selectByText(page: Page, selector: string, pattern: RegExp) {
  const find = () =>
    page
      .locator(`${selector} option`)
      .evaluateAll(
        (opts, src) => (opts as HTMLOptionElement[]).find((o) => new RegExp(src).test(o.textContent ?? ""))?.value ?? null,
        pattern.source,
      );
  await expect.poll(find, { message: `no option matching ${pattern} in ${selector}` }).not.toBeNull();
  await page.locator(selector).selectOption((await find())!);
}
