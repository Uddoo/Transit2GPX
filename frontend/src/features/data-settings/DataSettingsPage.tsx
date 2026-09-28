import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  cancelDatasetImport,
  compareRailDatasets,
  fetchDataQuality,
  RequestError,
  startRailDataImport,
  startDatasetImport,
} from "../../api/client";
import { useRailDataStatus } from "../journey-editor/useJourneyNetwork";
import { useDataStatus } from "./useDataStatus";

function datasetStatusLabel(status?: string) {
  switch (status) {
    case "ready":
      return "真实地铁数据已就绪";
    case "importing":
      return "正在校验并构建线路拓扑";
    case "failed":
      return "上次导入失败，请检查文件与质量报告";
    case "cancelled":
      return "上次导入已取消，可安全重新开始";
    default:
      return "尚未导入地铁数据";
  }
}

export function DataSettingsPage() {
  const query = useDataStatus();
  const queryClient = useQueryClient();
  const [directory, setDirectory] = useState("");
  const [railPbfPath, setRailPbfPath] = useState("");
  const [railGraphVersion, setRailGraphVersion] = useState("");
  const [railCompareFrom, setRailCompareFrom] = useState("");
  const [railCompareTo, setRailCompareTo] = useState("");
  const railStatus = useRailDataStatus();
  const importMutation = useMutation({
    mutationFn: startDatasetImport,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["data-status"] });
    },
  });
  const quality = useQuery({
    queryKey: ["data-quality"],
    queryFn: ({ signal }) => fetchDataQuality(signal),
    enabled: query.data?.status === "ready",
  });
  const cancelMutation = useMutation({
    mutationFn: cancelDatasetImport,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["data-status"] });
    },
  });
  const railImportMutation = useMutation({
    mutationFn: startRailDataImport,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["rail-data-status"] });
    },
  });
  const railCompareMutation = useMutation({ mutationFn: compareRailDatasets });
  const status = query.isError
    ? "本地服务未连接"
    : datasetStatusLabel(query.data?.status);
  const importError =
    importMutation.error instanceof RequestError
      ? importMutation.error.message
      : importMutation.isError
        ? "无法启动数据导入"
        : null;
  const isImporting = query.data?.status === "importing";

  return (
    <section className="simple-page" aria-labelledby="settings-title">
      <header className="page-heading">
        <h1 id="settings-title">数据与设置</h1>
        <p>管理本地地铁数据、质量报告与应用目录。</p>
        <Link className="button button--secondary" to="/setup?step=check">打开首次使用向导</Link>
      </header>
      <section className="settings-section settings-section--stacked" aria-labelledby="dataset-title">
        <div className="settings-section__heading">
          <div>
            <h2 id="dataset-title">CPTOND 地铁数据</h2>
            <p>{status}</p>
          </div>
          {query.data?.dataset ? <strong>{query.data.dataset}</strong> : null}
        </div>
        {query.isError ? (
          <div className="panel-message panel-message--error" role="alert">
            <p>无法读取本地数据状态。</p>
            <button className="button button--secondary" onClick={() => void query.refetch()} type="button">重试</button>
          </div>
        ) : null}

        {query.data?.status === "ready" ? (
          <>
            <dl className="dataset-facts">
              <div><dt>城市</dt><dd>{query.data.cities}</dd></div>
              <div><dt>采集时间</dt><dd>{query.data.captured_at ?? "未知"}</dd></div>
              <div><dt>许可</dt><dd>{query.data.license ?? "未知"}</dd></div>
              <div><dt>导入时间</dt><dd>{query.data.completed_at ? new Date(query.data.completed_at).toLocaleString() : "未知"}</dd></div>
              <div><dt>适配器</dt><dd>{query.data.importer_schema_version ?? "未知"}</dd></div>
              <div><dt>Checksum</dt><dd title={query.data.checksum ?? undefined}>{query.data.checksum?.slice(0, 12) ?? "未知"}</dd></div>
            </dl>
            {quality.data ? (
              <dl className="dataset-facts">
                <div><dt>可用线路</dt><dd>{quality.data.ready_lines}</dd></div>
                <div><dt>阻断线路</dt><dd>{quality.data.blocked_lines}</dd></div>
                <div><dt>阻断方向</dt><dd>{quality.data.blocked_variants}</dd></div>
              </dl>
            ) : quality.isError ? (
              <div className="panel-message panel-message--error" role="alert">
                <p>质量报告暂时无法读取。</p>
                <button className="button button--secondary" onClick={() => void quality.refetch()} type="button">重试质量报告</button>
              </div>
            ) : null}
            {quality.data?.issues?.length ? (
              <div className="quality-issues" role="region" aria-label="质量问题明细">
                <h3>质量问题</h3>
                <ul>
                  {quality.data.issues.map((issue) => (
                    <li key={`${issue.entity_type}-${issue.entity_id}-${issue.code}`}>
                      <strong>{issue.name}</strong>：{issue.message} <code>{issue.code}</code>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {query.data.source_url ? <p className="settings-note">数据来源：<a href={query.data.source_url} rel="noreferrer" target="_blank">数据集来源页面</a></p> : null}
          </>
        ) : (
          <form
            className="dataset-import-form"
            onSubmit={(event) => {
              event.preventDefault();
              importMutation.mutate(directory.trim());
            }}
          >
            <label className="field">
              <span className="field__label">地铁数据目录（本机绝对路径）</span>
              <input
                autoComplete="off"
                disabled={isImporting}
                onChange={(event) => setDirectory(event.target.value)}
                placeholder="/Users/you/Data/CPTOND-2025"
                spellCheck={false}
                value={directory}
              />
            </label>
            <p className="settings-note">
              支持 CPTOND v2 原包，也支持 Science Data Bank 的线路、分段、站点时序三文件。
            </p>
            <button
              className="button button--primary"
              disabled={!directory.trim() || importMutation.isPending || isImporting}
              type="submit"
            >
              {importMutation.isPending ? "正在审计目录" : "导入数据目录"}
            </button>
            {importMutation.data ? (
              <p className="form-message form-message--success" role="status">
                已发现 {importMutation.data.route_count ?? 0} 条线路、
                {importMutation.data.stop_count ?? 0} 条线路站点记录，后台开始构建。
              </p>
            ) : null}
            {isImporting && query.data ? (
              <div className="dataset-progress" aria-live="polite">
                <label htmlFor="dataset-import-progress">
                  已处理 {query.data.processed_cities} / {query.data.total_cities || "?"} 个城市
                </label>
                <progress
                  id="dataset-import-progress"
                  max={Math.max(query.data.total_cities, 1)}
                  value={query.data.processed_cities}
                />
                <span>{query.data.ready_lines} 条线路可用，{query.data.blocked_lines} 条被阻断</span>
              </div>
            ) : null}
            {isImporting && query.data?.import_id ? (
              <button
                className="button button--secondary"
                disabled={cancelMutation.isPending}
                onClick={() => cancelMutation.mutate(query.data.import_id as number)}
                type="button"
              >
                {cancelMutation.isPending ? "正在取消" : "取消导入"}
              </button>
            ) : null}
            {importError ? (
              <p className="form-message form-message--error" role="alert">{importError}</p>
            ) : null}
            {cancelMutation.isError ? (
              <p className="form-message form-message--error" role="alert">取消请求未生效，请刷新状态后重试。</p>
            ) : null}
            {query.data?.error_message ? (
              <p className="form-message form-message--error" role="alert">
                {query.data.error_message} {query.data.error_code ? `(${query.data.error_code})` : ""}
              </p>
            ) : null}
          </form>
        )}
      </section>

      <section className="settings-section settings-section--stacked" aria-labelledby="rail-dataset-title">
        <div className="settings-section__heading">
          <div>
            <h2 id="rail-dataset-title">OSM 中国铁路数据</h2>
            <p>
              {railStatus.isError
                ? "铁路状态读取失败"
                : railStatus.data?.status === "ready"
                  ? "铁路图、车站索引和本地路径服务已就绪"
                  : railStatus.data?.error_message ?? "铁路功能尚未启用"}
            </p>
          </div>
          {railStatus.data?.graph_version ? <strong>{railStatus.data.graph_version}</strong> : null}
        </div>
        {railStatus.data?.status === "ready" ? (
          <>
            <dl className="dataset-facts">
              <div><dt>铁路车站</dt><dd>{railStatus.data.station_count}</dd></div>
              <div><dt>图版本</dt><dd>{railStatus.data.graph_version}</dd></div>
              <div><dt>运行图版本</dt><dd>{railStatus.data.sidecar_graph_version}</dd></div>
              <div><dt>Profile</dt><dd>{railStatus.data.profile_version}</dd></div>
              <div><dt>提取范围</dt><dd>{railStatus.data.extract_region ?? "未知"}</dd></div>
              <div><dt>数据时间</dt><dd>{railStatus.data.source_timestamp ?? "未知"}</dd></div>
              <div><dt>许可</dt><dd>{railStatus.data.license ?? "ODbL-1.0"}</dd></div>
            </dl>
            <p className="settings-note">
              铁路轨迹来源：<a href="https://www.openstreetmap.org/copyright" rel="noreferrer" target="_blank">© OpenStreetMap contributors（ODbL）</a>。
            </p>
            <details className="rail-version-compare">
              <summary>比较铁路图版本</summary>
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  const toGraphVersion =
                    railCompareTo.trim() || railStatus.data?.graph_version;
                  if (!railCompareFrom.trim() || !toGraphVersion) return;
                  railCompareMutation.mutate({
                    fromGraphVersion: railCompareFrom.trim(),
                    toGraphVersion,
                  });
                }}
              >
                <label className="field">
                  <span className="field__label">原图版本</span>
                  <input
                    onChange={(event) => setRailCompareFrom(event.target.value)}
                    placeholder="例如 china-20260715-r2.1"
                    spellCheck={false}
                    value={railCompareFrom}
                  />
                </label>
                <label className="field">
                  <span className="field__label">目标图版本</span>
                  <input
                    onChange={(event) => setRailCompareTo(event.target.value)}
                    placeholder={railStatus.data.graph_version ?? "当前图版本"}
                    spellCheck={false}
                    value={railCompareTo}
                  />
                </label>
                <button
                  className="button button--secondary"
                  disabled={!railCompareFrom.trim() || railCompareMutation.isPending}
                  type="submit"
                >
                  {railCompareMutation.isPending ? "正在比较" : "查看版本差异"}
                </button>
              </form>
              {railCompareMutation.data ? (
                <div className="rail-version-compare__result" role="status">
                  <dl className="dataset-facts">
                    <div><dt>新增车站</dt><dd>{railCompareMutation.data.added_station_count}</dd></div>
                    <div><dt>移除车站</dt><dd>{railCompareMutation.data.removed_station_count}</dd></div>
                    <div><dt>属性变化</dt><dd>{railCompareMutation.data.changed_station_count}</dd></div>
                    <div><dt>不变车站</dt><dd>{railCompareMutation.data.unchanged_station_count}</dd></div>
                    <div><dt>受影响行程</dt><dd>{railCompareMutation.data.affected_journey_count}</dd></div>
                  </dl>
                  {railCompareMutation.data.samples.length ? (
                    <details>
                      <summary>查看差异样例</summary>
                      <ul>
                        {railCompareMutation.data.samples.map((sample) => (
                          <li key={`${sample.osm_type}-${sample.osm_id}`}>
                            {sample.from_name ?? "新增"} → {sample.to_name ?? "已移除"}
                            {" · "}{sample.changed_fields.join(", ")}
                          </li>
                        ))}
                      </ul>
                    </details>
                  ) : null}
                </div>
              ) : null}
              {railCompareMutation.isError ? (
                <p className="form-message form-message--error" role="alert">
                  {railCompareMutation.error instanceof RequestError
                    ? railCompareMutation.error.message
                    : "铁路图版本比较失败。"}
                </p>
              ) : null}
            </details>
          </>
        ) : railStatus.data?.status === "disabled" ? (
          <p className="settings-note">
            设置 <code>TRANSIT2FOG_RAIL_ENABLED=true</code>、
            <code>TRANSIT2FOG_RAIL_GRAPH_VERSION</code> 与图目录后重启本地服务；地铁功能不受影响。
          </p>
        ) : (
          <form
            className="dataset-import-form"
            onSubmit={(event) => {
              event.preventDefault();
              const graphVersion = railGraphVersion.trim() || railStatus.data?.graph_version;
              if (!graphVersion) return;
              railImportMutation.mutate({
                pbf_path: railPbfPath.trim(),
                graph_version: graphVersion,
              });
            }}
          >
            <label className="field">
              <span className="field__label">与建图一致的 PBF（本机绝对路径）</span>
              <input
                disabled={railStatus.data?.status === "importing"}
                onChange={(event) => setRailPbfPath(event.target.value)}
                placeholder="/Users/you/Data/china-latest.osm.pbf"
                spellCheck={false}
                value={railPbfPath}
              />
            </label>
            <label className="field">
              <span className="field__label">不可变图版本</span>
              <input
                disabled={railStatus.data?.status === "importing"}
                onChange={(event) => setRailGraphVersion(event.target.value)}
                placeholder={railStatus.data?.graph_version ?? "china-2026-08-r1"}
                spellCheck={false}
                value={railGraphVersion}
              />
            </label>
            <p className="settings-note">
              PBF SHA-256 必须与图目录中的 <code>transit2fog-graph.json</code> 完全一致；旧版 <code>metro2fog-graph.json</code> 仍可读取，导入不会覆盖就绪版本。
            </p>
            <button
              className="button button--primary"
              disabled={
                !railPbfPath.trim() ||
                !(railGraphVersion.trim() || railStatus.data?.graph_version) ||
                railImportMutation.isPending ||
                railStatus.data?.status === "importing"
              }
              type="submit"
            >
              {railStatus.data?.status === "importing" ? "正在构建车站索引" : "导入铁路车站索引"}
            </button>
            {railStatus.data?.status === "importing" ? (
              <div className="dataset-progress" aria-live="polite">
                <span>正在读取 PBF 并绑定图版本，请保持本地服务运行。</span>
                <progress />
              </div>
            ) : null}
            {railImportMutation.isError ? (
              <p className="form-message form-message--error" role="alert">
                {railImportMutation.error instanceof RequestError
                  ? railImportMutation.error.message
                  : "铁路车站索引导入启动失败。"}
              </p>
            ) : null}
          </form>
        )}
      </section>

      <section className="settings-section settings-section--stacked" aria-labelledby="map-privacy-title">
        <div>
          <h2 id="map-privacy-title">地图与隐私</h2>
          <p>默认在线底图会向 OpenStreetMap 请求当前视口瓦片，不包含乘车记录。</p>
        </div>
        <p className="settings-note">
          瓦片仅随交互视口加载，不做预取或离线批量下载；可通过
          <code>TRANSIT2FOG_MAP_TILES_ENABLED</code> 关闭，或配置自托管瓦片 URL。
        </p>
      </section>
    </section>
  );
}
