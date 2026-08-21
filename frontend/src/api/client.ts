import type { FeatureCollection, Geometry } from "geojson";

export type DataStatus = {
  status: "not_configured" | "importing" | "ready" | "failed" | "cancelled";
  ready_available: boolean;
  import_id: number | null;
  dataset: string | null;
  captured_at: string | null;
  license: string | null;
  source_url: string | null;
  checksum: string | null;
  importer_schema_version: string | null;
  cities: number;
  route_count: number;
  stop_count: number;
  total_cities: number;
  processed_cities: number;
  ready_lines: number;
  blocked_lines: number;
  imported_at: string | null;
  completed_at: string | null;
  error_code: string | null;
  error_message: string | null;
  quality_status: "not_available" | "checking" | "ready" | "blocked";
};

export type PublicConfig = {
  map: {
    tiles_enabled: boolean;
    tile_url: string;
    tile_attribution: string;
    max_zoom: number;
    external_tiles: boolean;
  };
};

export type MapFeatureProperties = Record<string, unknown>;
export type GeoJsonFeatureCollection = FeatureCollection<
  Geometry,
  MapFeatureProperties
>;

export type CityMap = {
  city_id: number;
  dataset_version_id: number;
  bbox: [number, number, number, number];
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

export type DatasetImport = {
  import_id: number;
  status: "staging" | "checking" | "ready" | "failed" | "cancelled";
  route_count: number | null;
  stop_count: number | null;
  checksum: string | null;
  total_cities: number;
  processed_cities: number;
  ready_lines: number;
  blocked_lines: number;
  error_code: string | null;
  error_message: string | null;
};

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

export type DataQuality = {
  dataset_version_id: number | null;
  ready_cities: number;
  blocked_cities: number;
  ready_lines: number;
  blocked_lines: number;
  ready_variants: number;
  blocked_variants: number;
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

export type City = {
  id: number;
  name_cn: string;
  name_en: string | null;
  center: [number, number];
  bbox: [number, number, number, number];
};

export type TransitLine = {
  id: number;
  city_id: number;
  name_cn: string;
  name_en: string | null;
  display_color: string | null;
};

export type Station = {
  id: number;
  city_id: number;
  name_cn: string;
  name_en: string | null;
  lon: number;
  lat: number;
};

export type PathCandidateLeg = {
  candidate_id: string;
  digest: string;
  dataset_version_id: number;
  line_id: number;
  route_variant_id: number;
  line_name: string;
  direction_name: string;
  distance_m: number;
  start_station_id: number;
  end_station_id: number;
  station_ids: number[];
  edge_ids: number[];
  reversed_edges: boolean[];
  warnings: Record<string, unknown>[];
};

export type PathCandidate = {
  candidate_id: string;
  digest: string;
  dataset_version_id: number;
  route_variant_id: number | null;
  line_name: string;
  direction_name: string;
  distance_m: number;
  station_count: number;
  station_ids: number[];
  edge_ids: number[];
  reversed_edges: boolean[];
  geometry: { type: "LineString"; coordinates: [number, number][] };
  warnings: Record<string, unknown>[];
  legs?: PathCandidateLeg[];
};

export type PathPreview = {
  status: "resolved" | "needs_review" | "unresolved";
  candidates: PathCandidate[];
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

export function previewPath(input: {
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

export type JourneyLeg = {
  id: number;
  leg_no: number;
  dataset_version_id: number;
  city_id: number;
  city_name: string;
  line_id: number;
  line_name: string;
  route_variant_id: number;
  start_station_id: number;
  start_station_name: string;
  end_station_id: number;
  end_station_name: string;
  direction: string | null;
  resolution_status: string;
  candidate_digest: string;
  edge_ids: number[];
  reversed_edges: boolean[];
  distance_m: number;
};

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

export type JourneyList = { items: Journey[]; total: number };

export function fetchJourneys(signal?: AbortSignal) {
  return requestJson<JourneyList>("/api/v1/journeys", { signal });
}

export type CreateJourneyInput = {
  traveled_at: string | null;
  note: string | null;
  source_type: "manual" | "map" | "csv";
  legs: {
    city_id: number;
    line_id: number;
    start_station_id: number;
    end_station_id: number;
    direction: string;
    via_station_ids: number[];
    candidate_id: string;
    candidate_digest: string;
  }[];
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

export async function deleteJourney(journeyId: number) {
  const response = await fetch(`/api/v1/journeys/${journeyId}`, { method: "DELETE" });
  if (!response.ok) {
    throw new RequestError(response.status);
  }
}

export type ExportOptions = {
  mode: "journeys" | "coverage";
  max_segment_length_m: 15 | 25 | 50 | null;
  journey_ids: number[];
  city_id?: number | null;
  line_id?: number | null;
  traveled_from?: string | null;
  traveled_to?: string | null;
};

export type ExportPreview = {
  preview_token: string;
  journey_count: number;
  edge_count: number;
  unique_edge_count: number;
  distance_m: number;
  track_count: number;
  segment_count: number;
  dataset_version_ids: number[];
  blocking_errors: string[];
  warnings: string[];
};

export function previewExport(input: ExportOptions) {
  return requestJson<ExportPreview>("/api/v1/exports/preview", {
    method: "POST",
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
  const filename = disposition.match(/filename="([^"]+)"/)?.[1] ?? "metro2fog.gpx";
  return { blob: await response.blob(), filename };
}

export type ImportBatch = {
  id: number;
  filename: string;
  encoding: string;
  total_rows: number;
  resolved_rows: number;
  review_rows: number;
  failed_rows: number;
  status: string;
  created_at: string;
  committed_at: string | null;
};

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
  selected_candidate_id: string | null;
  candidates: PathCandidate[];
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
