import type { FeatureCollection, Geometry } from "geojson";

import type { components } from "./generated";

type ApiSchema<Name extends keyof components["schemas"]> =
  components["schemas"][Name];

export type DataStatus = ApiSchema<"DataStatusResponse">;
export type PublicConfig = ApiSchema<"PublicConfigResponse">;

export type MapFeatureProperties = Record<string, unknown>;
export type GeoJsonFeatureCollection = FeatureCollection<
  Geometry,
  MapFeatureProperties
>;

export type CityMap = Omit<
  ApiSchema<"CityMapResponse">,
  "lines" | "stations"
> & {
  lines: GeoJsonFeatureCollection;
  stations: GeoJsonFeatureCollection;
};

export class RequestError extends Error {
  constructor(
    readonly status: number,
    readonly code?: string,
    message?: string,
  ) {
    super(message ?? `Request failed: ${status}`);
  }
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { Accept: "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as
      | { error?: { code?: string; message?: string } }
      | null;
    throw new RequestError(response.status, body?.error?.code, body?.error?.message);
  }
  return (await response.json()) as T;
}

export function fetchDataStatus({ signal }: { signal?: AbortSignal } = {}) {
  return requestJson<DataStatus>("/api/v1/data/status", { signal });
}

export function fetchPublicConfig({ signal }: { signal?: AbortSignal } = {}) {
  return requestJson<PublicConfig>("/api/v1/config/public", { signal });
}

export function fetchCityMap({
  cityId,
  lineId,
  signal,
}: {
  cityId: number;
  lineId?: number;
  signal?: AbortSignal;
}) {
  const search = new URLSearchParams();
  if (lineId !== undefined) {
    search.set("line_id", String(lineId));
  }
  const query = search.size > 0 ? `?${search.toString()}` : "";
  return requestJson<CityMap>(`/api/v1/cities/${cityId}/map${query}`, { signal });
}

export type DatasetImport = ApiSchema<"DatasetImportResponse">;

export function startDatasetImport(directory: string) {
  return requestJson<DatasetImport>("/api/v1/data/imports", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ directory }),
  });
}

export function cancelDatasetImport(importId: number) {
  return requestJson<DatasetImport>(`/api/v1/data/imports/${importId}/cancel`, {
    method: "POST",
  });
}

export type DataQuality = Omit<ApiSchema<"QualityResponse">, "issues"> & {
  issues: {
    entity_type: string;
    entity_id: number;
    name: string;
    code: string;
    message: string;
  }[];
};

export function fetchDataQuality(signal?: AbortSignal) {
  return requestJson<DataQuality>("/api/v1/data/quality", { signal });
}

export type City = ApiSchema<"CityResponse">;
export type TransitLine = ApiSchema<"LineResponse">;
export type Station = ApiSchema<"StationResponse">;
export type PathCandidateLeg = ApiSchema<"PathLegCandidateResponse">;

export type PathCandidate = Omit<
  ApiSchema<"PathCandidateResponse">,
  "geometry"
> & {
  geometry: { type: "LineString"; coordinates: [number, number][] };
};

export type PathPreview = {
  status: "resolved" | "needs_review" | "unresolved";
  candidates: PathCandidate[];
};

export type RailDataStatus = ApiSchema<"RailDataStatusResponse">;
export type RailStation = ApiSchema<"RailStationResponse">;
export type RailTrainType = ApiSchema<"RailPathPreviewRequest">["train_type"];

export type RailPathCandidate = Omit<
  ApiSchema<"RailPathCandidateResponse">,
  "geometry"
> & {
  geometry: { type: "LineString"; coordinates: [number, number][] };
};

export type RailPathPreview = {
  status: "resolved" | "needs_review" | "unresolved";
  candidates: RailPathCandidate[];
};

export function fetchCities({ signal }: { signal?: AbortSignal } = {}) {
  return requestJson<City[]>("/api/v1/cities", { signal });
}

export function fetchLines(cityId: number, signal?: AbortSignal) {
  return requestJson<TransitLine[]>(`/api/v1/cities/${cityId}/lines`, { signal });
}

export function fetchStations(lineId: number, signal?: AbortSignal) {
  return requestJson<Station[]>(`/api/v1/lines/${lineId}/stations`, { signal });
}

export function fetchCityStations(cityId: number, signal?: AbortSignal) {
  return requestJson<Station[]>(`/api/v1/cities/${cityId}/stations`, { signal });
}

export function searchStations({
  query,
  cityId,
  lineId,
  signal,
}: {
  query: string;
  cityId: number;
  lineId?: number;
  signal?: AbortSignal;
}) {
  const search = new URLSearchParams({
    q: query,
    city_id: String(cityId),
    limit: "30",
  });
  if (lineId !== undefined) {
    search.set("line_id", String(lineId));
  }
  return requestJson<Station[]>(`/api/v1/stations/search?${search.toString()}`, {
    signal,
  });
}

export function fetchRailDataStatus(signal?: AbortSignal) {
  return requestJson<RailDataStatus>("/api/v1/rail/data/status", { signal });
}

export type RailDataImport = Omit<
  ApiSchema<"RailDataImportResponse">,
  "status"
> & {
  status: "staging" | "building" | "ready" | "failed" | "retired";
};

export function startRailDataImport(input: {
  pbf_path: string;
  graph_version: string;
}) {
  return requestJson<RailDataImport>("/api/v1/rail/data/imports", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function fetchRailDataImport(importId: number, signal?: AbortSignal) {
  return requestJson<RailDataImport>(`/api/v1/rail/data/imports/${importId}`, {
    signal,
  });
}

export type RailStationDifferenceSample =
  ApiSchema<"RailStationDifferenceSample">;
export type RailDatasetDifference = ApiSchema<"RailDatasetDifferenceResponse">;

export function compareRailDatasets(input: {
  fromGraphVersion: string;
  toGraphVersion: string;
}) {
  const search = new URLSearchParams({
    from_graph_version: input.fromGraphVersion,
    to_graph_version: input.toGraphVersion,
  });
  return requestJson<RailDatasetDifference>(
    `/api/v1/rail/data/compare?${search.toString()}`,
  );
}

export function searchRailStations({
  query,
  railDatasetVersionId,
  provinceName,
  cityName,
  signal,
}: {
  query: string;
  railDatasetVersionId?: number;
  provinceName?: string;
  cityName?: string;
  signal?: AbortSignal;
}) {
  const search = new URLSearchParams({ q: query, limit: "30" });
  if (railDatasetVersionId !== undefined) {
    search.set("rail_dataset_version_id", String(railDatasetVersionId));
  }
  if (provinceName) search.set("province_name", provinceName);
  if (cityName) search.set("city_name", cityName);
  return requestJson<RailStation[]>(`/api/v1/rail/stations/search?${search.toString()}`, {
    signal,
  });
}

export function previewPath(input: {
  mode?: "metro";
  city_id: number;
  line_id: number | null;
  start_station_id: number;
  end_station_id: number;
  direction: string;
  via_station_ids: number[];
}) {
  return requestJson<PathPreview>("/api/v1/paths/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function previewRailPath(input: {
  mode: "rail";
  travel_date: string;
  train_no: string | null;
  train_type: RailTrainType;
  start_station_id: number;
  end_station_id: number;
  via_station_ids: number[];
  route_hint: string | null;
}) {
  return requestJson<RailPathPreview>("/api/v1/paths/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

type JourneyLegBase = {
  id: number;
  leg_no: number;
  direction: string | null;
  resolution_status: string;
  candidate_digest: string;
  edge_ids: number[];
  reversed_edges: boolean[];
  distance_m: number;
};

export type MetroJourneyLeg = JourneyLegBase & {
  transport_mode: "metro";
  dataset_version_id: number;
  rail_dataset_version_id: null;
  graph_version: null;
  city_id: number;
  city_name: string;
  line_id: number;
  line_name: string;
  route_variant_id: number;
  start_station_id: number;
  start_station_name: string;
  end_station_id: number;
  end_station_name: string;
  travel_date: null;
  train_no: null;
  train_type: null;
  routing_profile: null;
  route_hint: null;
  via_station_ids: number[];
  osm_way_ids: number[];
};

export type RailJourneyLeg = JourneyLegBase & {
  transport_mode: "rail";
  dataset_version_id: null;
  rail_dataset_version_id: number;
  graph_version: string;
  city_id: null;
  city_name: null;
  line_id: null;
  line_name: null;
  route_variant_id: null;
  start_station_id: number;
  start_station_name: string;
  end_station_id: number;
  end_station_name: string;
  travel_date: string;
  train_no: string | null;
  train_type: RailTrainType;
  timetable_provider: string;
  routing_profile: string;
  scoring_version: string;
  route_hint: string | null;
  score_details: Record<string, unknown>[];
  warnings: Record<string, unknown>[];
  via_station_ids: number[];
  osm_way_ids: number[];
};

export type JourneyLeg = MetroJourneyLeg | RailJourneyLeg;

export type Journey = {
  id: number;
  journey_code: string;
  traveled_at: string | null;
  source_type: string;
  note: string | null;
  created_at: string;
  updated_at: string;
  distance_m: number;
  legs: JourneyLeg[];
};

export type JourneyLegSummary = ApiSchema<"JourneyLegSummary">;
export type JourneySummary = ApiSchema<"JourneySummaryResponse">;
export type JourneyList = Omit<ApiSchema<"JourneyListResponse">, "items"> & { items: JourneySummary[] };
export type JourneyListOptions = {
  signal?: AbortSignal;
  q?: string;
  limit?: number;
  offset?: number;
  city_id?: number;
  line_id?: number;
  traveled_from?: string;
  traveled_to?: string;
};

export function fetchJourneys({ signal, ...options }: JourneyListOptions = {}) {
  const params = new URLSearchParams({ summary: "true" });
  Object.entries(options).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  return requestJson<JourneyList>(`/api/v1/journeys?${params.toString()}`, { signal });
}

export function fetchJourney(id: number, signal?: AbortSignal) {
  return requestJson<Journey>(`/api/v1/journeys/${id}`, { signal });
}

export type JourneyFilters = {
  cities: { id: number; name: string }[];
  lines: { id: number; name: string; city_id: number }[];
};

export function fetchJourneyFilters(signal?: AbortSignal) {
  return requestJson<JourneyFilters>("/api/v1/journeys/filters", { signal });
}

export type MetroJourneyLegInput = {
  mode?: "metro";
  city_id: number;
  line_id: number;
  start_station_id: number;
  end_station_id: number;
  direction: string;
  via_station_ids: number[];
  candidate_id: string;
  candidate_digest: string;
};

export type RailJourneyLegInput = {
  mode: "rail";
  travel_date: string;
  train_no: string | null;
  train_type: RailTrainType;
  start_station_id: number;
  end_station_id: number;
  via_station_ids: number[];
  route_hint: string | null;
  candidate_id: string;
  candidate_digest: string;
};

export type CreateJourneyInput = {
  traveled_at: string | null;
  note: string | null;
  source_type: "manual" | "map" | "csv";
  legs: (MetroJourneyLegInput | RailJourneyLegInput)[];
};

export function createJourney(input: CreateJourneyInput) {
  return requestJson<Journey>("/api/v1/journeys", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function patchJourney(
  journeyId: number,
  input: {
    traveled_at?: string | null;
    note?: string | null;
    expected_updated_at?: string;
  },
) {
  return requestJson<Journey>(`/api/v1/journeys/${journeyId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function reResolveJourney(journeyId: number) {
  return requestJson<Journey>(`/api/v1/journeys/${journeyId}/re-resolve`, {
    method: "POST",
  });
}

export type RailRecomputeLegPreview = {
  leg_no: number;
  source_graph_version: string;
  target_graph_version: string;
  station_names: string[];
  status: "resolved" | "needs_review" | "unresolved";
  candidates: RailPathCandidate[];
};

export type RailRecomputePreview = {
  journey_id: number;
  target_graph_version: string;
  target_profile_version: string;
  legs: RailRecomputeLegPreview[];
};

export type RailRecomputeInput = {
  target_graph_version: string;
  selections: {
    leg_no: number;
    candidate_id: string;
    candidate_digest: string;
  }[];
};

export function previewRailRecompute(journeyId: number) {
  return requestJson<RailRecomputePreview>(
    `/api/v1/journeys/${journeyId}/rail-recompute/preview`,
    { method: "POST" },
  );
}

export function confirmRailRecompute(
  journeyId: number,
  input: RailRecomputeInput,
) {
  return requestJson<Journey>(
    `/api/v1/journeys/${journeyId}/rail-recompute`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
}

export async function deleteJourney(journeyId: number) {
  const response = await fetch(`/api/v1/journeys/${journeyId}`, { method: "DELETE" });
  if (!response.ok) {
    throw new RequestError(response.status);
  }
}

export type ExportOptions = {
  mode: "journeys" | "coverage";
  max_segment_length_m: 15 | 25 | 50 | null;
  rail_max_segment_length_m: 100 | 200 | 500 | null;
  journey_ids: number[];
  city_id?: number | null;
  line_id?: number | null;
  traveled_from?: string | null;
  traveled_to?: string | null;
};

export type ExportPreview = ApiSchema<"ExportPreviewResponse">;

export function previewExport(input: ExportOptions, signal?: AbortSignal) {
  return requestJson<ExportPreview>("/api/v1/exports/preview", {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function downloadGpx(input: ExportOptions & { preview_token: string }) {
  const response = await fetch("/api/v1/exports/gpx", {
    method: "POST",
    headers: { Accept: "application/gpx+xml", "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as
      | { error?: { code?: string; message?: string } }
      | null;
    throw new RequestError(response.status, body?.error?.code, body?.error?.message);
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = disposition.match(/filename="([^"]+)"/)?.[1] ?? "transit2fog.gpx";
  return { blob: await response.blob(), filename };
}

export type ImportBatch = ApiSchema<"ImportBatchResponse">;

export type ImportRow = {
  id: number;
  row_no: number;
  raw: Record<string, string>;
  normalized: Record<string, string>;
  resolution_status: string;
  matched_city_id: number | null;
  matched_line_id: number | null;
  matched_start_station_id: number | null;
  matched_end_station_id: number | null;
  matched_rail_start_station_id: number | null;
  matched_rail_end_station_id: number | null;
  selected_candidate_id: string | null;
  candidates: (PathCandidate | RailPathCandidate)[];
  error_code: string | null;
  error_message: string | null;
};

export type ImportRows = { items: ImportRow[]; total: number };

export function createImportBatch(file: File) {
  const body = new FormData();
  body.append("file", file);
  return requestJson<ImportBatch>("/api/v1/import-batches", { method: "POST", body });
}

export function fetchImportBatch(batchId: number, signal?: AbortSignal) {
  return requestJson<ImportBatch>(`/api/v1/import-batches/${batchId}`, { signal });
}

export function cancelImportBatch(batchId: number) {
  return requestJson<ImportBatch>(`/api/v1/import-batches/${batchId}/cancel`, { method: "POST" });
}

export function resumeImportBatch(batchId: number) {
  return requestJson<ImportBatch>(`/api/v1/import-batches/${batchId}/resume`, { method: "POST" });
}

export function fetchImportRows(
  batchId: number,
  status: string,
  limit: number,
  offset: number,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (status) query.set("status", status);
  return requestJson<ImportRows>(`/api/v1/import-batches/${batchId}/rows?${query}`, { signal });
}

export function patchImportRow(
  batchId: number,
  rowId: number,
  input: Record<string, string | boolean | null>,
) {
  return requestJson<ImportRow>(`/api/v1/import-batches/${batchId}/rows/${rowId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function commitImportBatch(batchId: number, strategy: "all" | "resolved_only") {
  return requestJson<ImportBatch>(`/api/v1/import-batches/${batchId}/commit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ strategy }),
  });
}

export type SetupState = ApiSchema<"SetupState">;
export type SetupChecks = ApiSchema<"SetupChecks">;
export type SetupProgress = ApiSchema<"SetupProgress">;
export type SetupProgressPatch = Partial<ApiSchema<"SetupProgressPatch">>;
export type RailSetupConfig = ApiSchema<"RailSetupConfig">;
export type RailServiceState = ApiSchema<"RailServiceState">;
export type ComponentState = ApiSchema<"ComponentState">;
export type PackPreview = ApiSchema<"PackPreview">;
export type SetupStep = NonNullable<SetupProgress["step"]>;

export function fetchSetup(signal?: AbortSignal) {
  return requestJson<SetupState>("/api/v1/setup", { signal });
}
export function fetchSetupChecks(signal?: AbortSignal) {
  return requestJson<SetupChecks>("/api/v1/setup/checks", { signal });
}
export function updateSetupProgress(input: SetupProgressPatch) {
  return requestJson<SetupProgress>("/api/v1/setup/progress", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
}
export function checkRailSetup(input: RailSetupConfig) {
  return requestJson<SetupChecks>("/api/v1/setup/rail/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
}
export function startSetupRailService(input: RailSetupConfig) {
  return requestJson<RailServiceState>("/api/v1/setup/rail/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) });
}

export function prepareRailComponents() {
  return requestJson<ComponentState>("/api/v1/setup/rail/components", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ install: true }) });
}

export function inspectCityPack(file: File) {
  const body = new FormData();
  body.append("file", file);
  return requestJson<PackPreview>("/api/v1/data/city-packs/inspect", { method: "POST", body });
}

export function installCityPack(packageId: string) {
  return requestJson<ApiSchema<"PackInstallResult">>("/api/v1/data/city-packs/install", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ package_id: packageId }) });
}
