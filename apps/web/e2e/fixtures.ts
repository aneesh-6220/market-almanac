import { expect, test as base } from "@playwright/test";

import { API } from "./helpers";

/**
 * Live runs against a deployed API (E2E_API_URL set to something other than localhost) are paced.
 *
 * The free-tier API allows 120 requests a minute per client address and a market page makes about nine, so a suite
 * that runs flat out measures the rate limiter instead of the product. Supported workload for a production run:
 * one worker (`--workers=1`), and at most `E2E_API_BUDGET_PER_MINUTE` (default 100) API requests in any rolling
 * minute, which this fixture enforces by delaying the start of a test until the previous minute leaves room for
 * one more page. Direct `request.get` calls also wait out a 429 or 503 (the same Retry-After contract the web app
 * follows) instead of failing on the first transient response. Local runs are untouched.
 */
const remote = !/^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/.test(API);
const BUDGET = Number(process.env.E2E_API_BUDGET_PER_MINUTE ?? 100);
const TEST_COST = Number(process.env.E2E_API_REQUESTS_PER_TEST ?? 45); // most requests one test makes (see the log line)
const stamps: number[] = []; // request times in this worker process
let total = 0;
const note = () => {
  stamps.push(Date.now());
  total++;
};

const recent = () => {
  const now = Date.now();
  while (stamps.length && now - stamps[0] > 60_000) stamps.shift();
  return stamps.length;
};
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export const test = base.extend<{ paced: void }>({
  paced: [
    async ({ context, request }, use, info) => {
      const before = total;
      if (remote) {
        while (recent() + TEST_COST > BUDGET) await sleep(1000);
                context.on("request", (r) => {
          if (r.url().startsWith(`${API}/`)) note();
        });
        const get = request.get.bind(request);
        request.get = (async (url: string, options?: Parameters<typeof get>[1]) => {
          for (let attempt = 0; ; attempt++) {
            note();
            const res = await get(url, options);
            if ((res.status() !== 429 && res.status() !== 503) || attempt >= 4) return res;
            const wait = Number(res.headers()["retry-after"] ?? 5);
            await sleep(Math.min(Math.max(wait, 1), 65) * 1000);
          }
        }) as typeof request.get;
      }
      await use();
      if (remote) console.log(`[api requests] ${total - before} in "${info.title}"`);
    },
    { auto: true, timeout: 180_000 }, // waiting for rate-limit headroom is not part of the test's own budget
  ],
});
export { expect };
