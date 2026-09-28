import type { SetupState } from "../api/client";

export function initialSetupState(): SetupState {
  return {
    progress: { step: "check", dismissed: false, completed: false, rail_skipped: false }, should_show: true,
    metro: { status: "not_configured", ready_available: false, import_id: null, dataset: null, captured_at: null, license: null, source_url: null, checksum: null, importer_schema_version: null, cities: 0, route_count: 0, stop_count: 0, total_cities: 0, processed_cities: 0, ready_lines: 0, blocked_lines: 0, imported_at: null, completed_at: null, error_code: null, error_message: null, quality_status: "not_available" },
    rail: { status: "disabled", enabled: false, sidecar_available: false, rail_dataset_version_id: null, dataset_status: null, station_count: 0, graph_version: null, profile_version: null, sidecar_graph_version: null, sidecar_profile_version: null, sidecar_pbf_checksum: null, pbf_checksum: null, source_url: null, source_timestamp: null, extract_region: null, license: null, profiles: [], bbox: null, error_code: null, error_message: null },
    service: { status: "idle", error_code: null, message: null },
    rail_config: { graph_root: "/tmp/graphs", graph_version: "active", pbf_path: "/tmp/rail.osm.pbf", jar_path: "/tmp/openrailrouting.jar", java_home: null },
    metro_directory: "", log_path: "/tmp/logs/rail-sidecar.log", locked_fields: [], rail_start_allowed: true,
  };
}
export const readyChecks = { can_continue: true, checks: [{ id: "service", title: "本地服务", status: "passed", detail: "服务连接正常", remedy: null }, { id: "database", title: "本地数据库", status: "passed", detail: "结构与当前版本一致", remedy: null }, { id: "storage", title: "数据目录", status: "passed", detail: "可保存行程和导入任务", remedy: null }, { id: "disk", title: "可用空间", status: "passed", detail: "剩余 30 GB", remedy: null }] };
