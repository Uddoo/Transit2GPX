import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  cancelDatasetImport,
  fetchDataQuality,
  RequestError,
  startDatasetImport,
} from "../../api/client";
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

      <section className="settings-section settings-section--stacked" aria-labelledby="map-privacy-title">
        <div>
          <h2 id="map-privacy-title">地图与隐私</h2>
          <p>默认在线底图会向 OpenStreetMap 请求当前视口瓦片，不包含乘车记录。</p>
        </div>
        <p className="settings-note">
          瓦片仅随交互视口加载，不做预取或离线批量下载；可通过
          <code>METRO2FOG_MAP_TILES_ENABLED</code> 关闭，或配置自托管瓦片 URL。
        </p>
      </section>
    </section>
  );
}
