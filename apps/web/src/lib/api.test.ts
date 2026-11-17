import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { ApiError, apiGet, apiUrl } from "./api";

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
