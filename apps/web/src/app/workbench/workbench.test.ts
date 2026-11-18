import { describe, expect, it } from "vitest";

import { type Draft, toYaml } from "./workbench-client";

const base: Draft = {
  id: "t-study-v1",
  title: 'A "quoted" title: with colon',
  question: "Does weather help forecasts of prices?",
  hypothesis: "Family B beats family A on loss.",
  estimand: "Loss ratio B over A, country-balanced.",
  studyType: "predictive",
  confirmatory: true,
  countries: ["ETH", "UGA"],
  categories: "cereals and tubers",
  horizons: [1, 3],
  testStart: "2022-01-01",
  robustness: ["price_lag_0"],
  controls: ["weather_time_shift_60"],
  seed: 7,
};

describe("toYaml", () => {
  it("emits one hypothesis per horizon and escapes free text", () => {
    const y = toYaml(base);
    expect(y).toContain("evidence_class: confirmatory");
    expect(y).toContain("countries: [ETH, UGA]");
    expect(y).toContain('title: "A \\"quoted\\" title: with colon"');
    expect(y.match(/- id: H\d/g)).toHaveLength(2);
    expect(y).toContain("negative_controls: [weather_time_shift_60]");
  });
  it("omits forecast-only sections for descriptive studies", () => {
    const y = toYaml({
      ...base,
      studyType: "descriptive",
      confirmatory: false,
    });
    expect(y).not.toContain("predictive:");
    expect(y).not.toContain("negative_controls");
    expect(y).toContain("descriptive:");
  });
});
