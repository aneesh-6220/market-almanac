import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import {
  ApiError,
  apiGet,
  apiUrl,
  loadingLabel,
  normalizeApiUrl,
  parseRetryAfter,
  retryDelayMs,
  shouldRetry,
  TRANSIENT_RETRIES,
} from "./api";

const ok = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));

afterEach(() => vi.unstubAllGlobals());

describe("apiUrl", () => {
  it("drops empty parameters and encodes the rest", () => {
    const u = new URL(apiUrl("/api/v1/prices", { series_id: "ps_1", country: "", limit: 10, x: undefined }));
    expect(u.pathname).toBe("/api/v1/prices");
    expect(u.searchParams.get("series_id")).toBe("ps_1");
    expect(u.searchParams.has("country")).toBe(false);
    expect(u.searchParams.get("limit")).toBe("10");
  });
});

describe("apiGet", () => {
  it("validates responses with the schema and applies defaults", async () => {
    vi.stubGlobal("fetch", vi.fn(() => ok({ name: "x" })));
    const data = await apiGet("/t", z.object({ name: z.string(), tags: z.array(z.string()).default([]) }));
    expect(data).toEqual({ name: "x", tags: [] });
  });

  it("surfaces the API error detail with its status", async () => {
    vi.stubGlobal("fetch", vi.fn(() => ok({ detail: "no data-quality report yet" }, 404)));
    await expect(apiGet("/t", z.object({}))).rejects.toMatchObject({ status: 404, message: "no data-quality report yet" });
  });

  it("rejects responses with an unexpected shape rather than rendering them", async () => {
    vi.stubGlobal("fetch", vi.fn(() => ok({ name: 3 })));
    await expect(apiGet("/t", z.object({ name: z.string() }))).rejects.toBeInstanceOf(ApiError);
  });

  it("reports an unreachable API as status 0", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("fetch failed"))));
    await expect(apiGet("/t", z.object({}))).rejects.toMatchObject({ status: 0 });
  });
});

describe("normalizeApiUrl", () => {
  it("upgrades remote http to https and trims slashes", () => {
    expect(normalizeApiUrl("http://market-almanac.onrender.com/")).toBe("https://market-almanac.onrender.com");
    expect(normalizeApiUrl(" https://api.example.org// ")).toBe("https://api.example.org");
  });
  it("keeps local development URLs and defaults", () => {
    expect(normalizeApiUrl("http://localhost:8000")).toBe("http://localhost:8000");
    expect(normalizeApiUrl("http://127.0.0.1:8000/")).toBe("http://127.0.0.1:8000");
    expect(normalizeApiUrl(undefined)).toBe("http://localhost:8000");
  });
});

describe("transient failures", () => {
  const busy = () =>
    Promise.resolve(
      new Response(JSON.stringify({ error: "busy", detail: "The server is busy with other requests; retry shortly." }), {
        status: 503,
        headers: { "content-type": "application/json", "retry-after": "5" },
      }),
    );

  it("reads Retry-After from a 503 and marks the error transient", async () => {
    vi.stubGlobal("fetch", vi.fn(busy));
    const err = await apiGet("/t", z.object({})).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 503, retryAfterMs: 5000, transient: true });
  });

  it("parses Retry-After as seconds or a date, clamped to 1-30 s, and ignores nonsense", () => {
    expect(parseRetryAfter("5")).toBe(5000);
    expect(parseRetryAfter("0")).toBe(1000);
    expect(parseRetryAfter("600")).toBe(30000);
    expect(parseRetryAfter(new Date(1_000_000 + 12_000).toUTCString(), 1_000_000)).toBe(12000);
    expect(parseRetryAfter("soon")).toBeUndefined();
    expect(parseRetryAfter(null)).toBeUndefined();
  });

  it("retries a busy, starting or unreachable service a bounded number of times, honouring Retry-After", () => {
    const e503 = new ApiError(503, "busy", 5000);
    expect(shouldRetry(0, e503)).toBe(true);
    expect(shouldRetry(TRANSIENT_RETRIES - 1, e503)).toBe(true);
    expect(shouldRetry(TRANSIENT_RETRIES, e503)).toBe(false); // never loops forever
    expect(retryDelayMs(0, e503)).toBe(5000);
    expect(shouldRetry(0, new ApiError(0, "offline"))).toBe(true);
    expect(shouldRetry(0, new ApiError(502, "bad gateway"))).toBe(true);
    expect(retryDelayMs(0, new ApiError(0, "x"))).toBe(1000);
    expect(retryDelayMs(10, new ApiError(0, "x"))).toBe(10000);
  });

  it("does not retry what waiting cannot fix, and retries a plain server error once", () => {
    expect(shouldRetry(0, new ApiError(404, "unknown series"))).toBe(false);
    expect(shouldRetry(0, new ApiError(422, "invalid"))).toBe(false);
    expect(shouldRetry(0, new ApiError(500, "boom"))).toBe(true);
    expect(shouldRetry(1, new ApiError(500, "boom"))).toBe(false);
  });

  it("turns a stalled request into an error instead of an endless spinner", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new DOMException("timed out", "TimeoutError"))));
    await expect(apiGet("/t", z.object({}))).rejects.toMatchObject({ status: 0, transient: true });
  });

  it("says when a panel is being retried", () => {
    expect(loadingLabel({ failureCount: 0 }, "Loading prices")).toBe("Loading prices");
    expect(loadingLabel({ failureCount: 2 }, "Loading prices")).toContain("retrying");
  });
});
