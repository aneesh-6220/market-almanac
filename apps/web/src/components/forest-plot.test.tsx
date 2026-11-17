import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Comparison } from "@/lib/api";

import { ForestPlot } from "./forest-plot";

const row = (over: Partial<Comparison>): Comparison =>
  ({
    role: "primary",
    task: "regression",
    horizon: 1,
    model_a: "ridge_A",
    model_b: "ridge_B",
    relative_loss_b_vs_a: 0.76,
    mean_loss_a: 0.0046,
    mean_loss_b: 0.0035,
    n_rows: 704,
    dm: { stat: 2.67, p_value_two_sided: 0.0086, p_value_b_better: 0.0043, n_periods: 118, lags: 4 },
    bootstrap_loss_ratio: { ratio: 0.76, ci_low: 0.56, ci_high: 0.86 },
    subperiods: [],
    verdict: "improved",
    reason: "",
    ...over,
  }) as Comparison;

describe("ForestPlot", () => {
  it("shows each comparison with its p-value and verdict", () => {
    render(
      <ForestPlot
        rows={[
          row({}),
          row({ task: "classification", model_a: "logit_A", model_b: "logit_B", verdict: "not_improved", dm: { stat: 0.1, p_value_two_sided: 0.9, p_value_b_better: 0.451, n_periods: 118, lags: 4 } }),
        ]}
      />,
    );
    expect(screen.getByRole("figure", { name: /forest plot/i })).toBeInTheDocument();
    expect(screen.getByText("0.004")).toBeInTheDocument();
    expect(screen.getByText("0.451")).toBeInTheDocument();
    expect(screen.getByText("Improved")).toBeInTheDocument();
    expect(screen.getByText("Not improved")).toBeInTheDocument();
    expect(screen.getAllByTitle(/Loss ratio 0.76; 95% CI 0.56–0.86/)).toHaveLength(2);
  });

  it("still renders when the bootstrap interval is unavailable", () => {
    render(<ForestPlot rows={[row({ verdict: "insufficient_evidence", bootstrap_loss_ratio: { ratio: null, ci_low: null, ci_high: null } })]} />);
    expect(screen.getByText("Insufficient")).toBeInTheDocument();
    expect(screen.getByTitle(/95% CI —–—/)).toBeInTheDocument();
  });
});
