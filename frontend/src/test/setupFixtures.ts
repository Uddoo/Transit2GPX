import type { SetupState, CityDownloadState, CityCatalog } from "../api/client";

export function initialSetupState(): SetupState {
  return {
    raw_import_available: true,
    progress: { step: "check", dismissed: false, completed: false, rail_skipped: false }, should_show: true,
    metro: { status: "not_configured", ready_available: false, import_id: null, dataset: null, captured_at: null, license: null, source_url: null, checksum: null, importer_schema_version: null, cities: 0, route_count: 0, stop_count: 0, total_cities: 0, processed_cities: 0, ready_lines: 0, blocked_lines: 0, imported_at: null, completed_at: null, error_code: null, error_message: null, quality_status: "not_available" },
    rail: { status: "disabled", enabled: false, sidecar_available: false, rail_dataset_version_id: null, dataset_status: null, station_count: 0, graph_version: null, profile_version: null, sidecar_graph_version: null, sidecar_profile_version: null, sidecar_pbf_checksum: null, pbf_checksum: null, source_url: null, source_timestamp: null, extract_region: null, license: null, profiles: [], bbox: null, error_code: null, error_message: null },
    service: { status: "idle", error_code: null, message: null },
    components: { status: "unavailable", downloaded_bytes: 0, total_bytes: 0, message: null, jar_path: null, java_home: null },
    rail_config: { graph_root: "/tmp/graphs", graph_version: "active", pbf_path: "/tmp/rail.osm.pbf", jar_path: "/tmp/openrailrouting.jar", java_home: null },
    metro_directory: "", log_path: "/tmp/logs/rail-sidecar.log", locked_fields: [], rail_start_allowed: true,
  };
}
export const readyChecks = { can_continue: true, checks: [{ id: "service", title: "本地服务", status: "passed", detail: "服务连接正常", remedy: null }, { id: "database", title: "本地数据库", status: "passed", detail: "结构与当前版本一致", remedy: null }, { id: "storage", title: "数据目录", status: "passed", detail: "可保存行程和导入任务", remedy: null }, { id: "disk", title: "可用空间", status: "passed", detail: "剩余 30 GB", remedy: null }] };

export const idleCityDownload: CityDownloadState = { status: "idle", city_code: null, city_name: null, downloaded_bytes: 0, total_bytes: 0, message: null, dataset_id: null };
export const catalogFixture: CityCatalog = {
  format: "transit2fog-city-catalog-v1", release_tag: "metro-data-2025-06-r1", data_snapshot: "2025-06", license: "CC BY 4.0", scope_note: "Test fixture",
  packages: [{city_code: "021", city_name: "上海", city_name_en: "Shanghai", file: "metro-021-shanghai-2025-06-r1.t2fcity", url: "https://github.com/Uddoo/transit2fog/releases/download/metro-data-2025-06-r1/metro-021-shanghai-2025-06-r1.t2fcity", size: 692890, sha256: "a".repeat(64), stations: 448, ready_variants: 66, blocked_variants: 0,
    manifest: {format: "transit2fog-city-v1", city_code: "021", city_name: "上海", network_sha256: "b".repeat(64), source: {name: "CPTOND", version: "2025-06-r1", url: "https://example.org", license: "CC BY 4.0", captured_at: "2025-06", checksum: "source", importer: "cptond-v2.3", attribution: "Test attribution"}},
  }],
};
