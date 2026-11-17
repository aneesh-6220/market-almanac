import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { ErrorState, VerdictBadge } from "./ui";

describe("VerdictBadge", () => {
  it.each([
    ["improved", "Improved"],
    ["not_improved", "Not improved"],
    ["inconsistent", "Inconsistent"],
    ["insufficient_evidence", "Insufficient"],
  ])("labels %s in plain language", (v, label) => {
    render(<VerdictBadge verdict={v} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("says 'Not run' when there is no verdict", () => {
    render(<VerdictBadge verdict={null} />);
    expect(screen.getByText("Not run")).toBeInTheDocument();
  });
});

describe("ErrorState", () => {
  it("explains how to fix an unreachable API", () => {
    render(<ErrorState error={new ApiError(0, "Cannot reach the Market Almanac API")} what="prices" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Could not load prices.");
    expect(screen.getByRole("alert")).toHaveTextContent("NEXT_PUBLIC_API_URL");
  });

  it("shows server messages without a stack trace", () => {
    render(<ErrorState error={new ApiError(404, "no predictions stored for this experiment")} what="backtest predictions" />);
    expect(screen.getByRole("alert")).toHaveTextContent("no predictions stored");
    expect(screen.getByRole("alert")).not.toHaveTextContent("NEXT_PUBLIC_API_URL");
  });
});
