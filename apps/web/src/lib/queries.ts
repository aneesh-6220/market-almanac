"use client";

import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import {
  AgriPageSchema,
  apiGet,
  CommoditySchema,
  CountrySchema,
  CoverageSchema,
  ExperimentDetailSchema,
  ExperimentSummarySchema,
  ForecastSchema,
  IndicatorPageSchema,
  JobSchema,
  LagSchema,
  MarketSchema,
  PredictionPageSchema,
  PricePageSchema,
  QualitySchema,
  SeriesSchema,
  SnapshotSchema,
  SourceSchema,
  StatusSchema,
  WeatherSchema,
} from "./api";

const long = { staleTime: 5 * 60_000 };

export const useStatus = () => useQuery({ queryKey: ["status"], queryFn: () => apiGet("/api/v1/status", StatusSchema), ...long });
export const useSources = () =>
  useQuery({ queryKey: ["sources"], queryFn: () => apiGet("/api/v1/sources", z.array(SourceSchema)), ...long });
export const useCountries = () =>
  useQuery({ queryKey: ["countries"], queryFn: () => apiGet("/api/v1/countries", z.array(CountrySchema)), ...long });
export const useCommodities = (country?: string) =>
  useQuery({
    queryKey: ["commodities", country],
    queryFn: () => apiGet("/api/v1/commodities", z.array(CommoditySchema), { country }),
    enabled: !!country,
    ...long,
  });
export const useMarkets = (country?: string, commodity?: string) =>
  useQuery({
    queryKey: ["markets", country, commodity],
    queryFn: () => apiGet("/api/v1/markets", z.array(MarketSchema), { country, commodity }),
    enabled: !!country,
    ...long,
  });
export const useSeries = (params: { country?: string; market?: string; commodity?: string }) =>
  useQuery({
    queryKey: ["series", params],
    queryFn: () => apiGet("/api/v1/series", z.array(SeriesSchema), params),
    enabled: !!(params.country || params.market),
    ...long,
  });
export const usePrices = (seriesId?: string) =>
  useQuery({
    queryKey: ["prices", seriesId],
    queryFn: () => apiGet("/api/v1/prices", PricePageSchema, { series_id: seriesId, limit: 5000 }),
    enabled: !!seriesId,
    ...long,
  });
export const useWeather = (locationId?: string | null) =>
  useQuery({
    queryKey: ["weather", locationId],
    queryFn: () => apiGet("/api/v1/weather", WeatherSchema, { location_id: locationId ?? undefined }),
    enabled: !!locationId,
    retry: false,
    ...long,
  });
export const useIndicators = (country?: string) =>
  useQuery({
    queryKey: ["indicators", country],
    queryFn: () => apiGet("/api/v1/economic-indicators", IndicatorPageSchema, { country, limit: 5000 }),
    enabled: !!country,
    ...long,
  });
export const useAgriculture = (country?: string, item?: string | null) =>
  useQuery({
    queryKey: ["agri", country, item],
    queryFn: () => apiGet("/api/v1/agriculture", AgriPageSchema, { country, item: item ?? undefined }),
    enabled: !!country && !!item,
    ...long,
  });
export const useLags = (seriesId?: string) =>
  useQuery({
    queryKey: ["lags", seriesId],
    queryFn: () => apiGet(`/api/v1/series/${seriesId}/lagged-relationships`, LagSchema, { max_lag: 6 }),
    enabled: !!seriesId,
    retry: false,
    ...long,
  });
export const useCoverage = (country?: string, commodity?: string) =>
  useQuery({
    queryKey: ["coverage", country, commodity],
    queryFn: () => apiGet("/api/v1/coverage", CoverageSchema, { country, commodity }),
    enabled: !!country,
    ...long,
  });
export const useExperiments = () =>
  useQuery({
    queryKey: ["experiments"],
    queryFn: () => apiGet("/api/v1/experiments", z.array(ExperimentSummarySchema)),
    ...long,
  });
export const useExperiment = (id?: string | null) =>
  useQuery({
    queryKey: ["experiment", id],
    queryFn: () => apiGet(`/api/v1/experiments/${id}`, ExperimentDetailSchema),
    enabled: !!id,
    ...long,
  });
export const useForecasts = (params: { experiment_id?: string; series_id?: string }) =>
  useQuery({
    queryKey: ["forecasts", params],
    queryFn: () => apiGet("/api/v1/forecasts", z.array(ForecastSchema), params),
    enabled: !!(params.experiment_id || params.series_id),
    ...long,
  });
export const usePredictions = (p: { experiment_id?: string; task: string; horizon: number; series_id?: string; models?: string }) =>
  useQuery({
    queryKey: ["predictions", p],
    queryFn: () => apiGet("/api/v1/predictions", PredictionPageSchema, { ...p, limit: 20000 }),
    enabled: !!p.experiment_id,
    ...long,
  });
export const useQuality = (params: { series_id?: string; country?: string; eligible_only?: boolean; limit?: number } = {}) =>
  useQuery({
    queryKey: ["quality", params],
    queryFn: () => apiGet("/api/v1/data-quality", QualitySchema, params),
    retry: false,
    ...long,
  });
export const useSnapshots = () =>
  useQuery({ queryKey: ["snapshots"], queryFn: () => apiGet("/api/v1/snapshots", z.array(SnapshotSchema)), ...long });
export const useJobs = () =>
  useQuery({ queryKey: ["jobs"], queryFn: () => apiGet("/api/v1/ingestion-jobs", z.array(JobSchema)), ...long });
