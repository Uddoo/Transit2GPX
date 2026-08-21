import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  commitImportBatch,
  createImportBatch,
  fetchImportBatch,
  fetchImportRows,
  patchImportRow,
  type ImportRow,
} from "../../api/client";
import { ModalDialog } from "../../components/ModalDialog";

const PAGE_SIZE = 50;

const statusLabels: Record<string, string> = {
  resolved: "已解析",
  needs_review: "需人工确认",
  unresolved: "未解析",
  ignored: "已忽略",
  committed: "已提交",
};

const METRO_REPAIR_FIELDS = [
  "mode",
  "travel_date",
  "city",
  "line",
  "from_station",
  "to_station",
  "direction",
  "via_stations",
  "note",
] as const;
const RAIL_REPAIR_FIELDS = [
  "mode",
  "travel_date",
  "train_no",
  "train_type",
  "from_station",
  "to_station",
  "via_stations",
  "route_hint",
  "note",
] as const;

export function CsvImportPage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const [batchId, setBatchId] = useState<number>();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(0);
  const [editing, setEditing] = useState<ImportRow>();
  const upload = useMutation({
    mutationFn: createImportBatch,
    onSuccess: (newBatch) => {
      setBatchId(newBatch.id);
      setStatus("");
      setPage(0);
    },
  });
  const batch = useQuery({
    queryKey: ["import-batch", batchId],
    queryFn: ({ signal }) => fetchImportBatch(batchId as number, signal),
    enabled: batchId !== undefined,
  });
  const rows = useQuery({
    queryKey: ["import-rows", batchId, status, page],
    queryFn: ({ signal }) =>
      fetchImportRows(batchId as number, status, PAGE_SIZE, page * PAGE_SIZE, signal),
    enabled: batchId !== undefined,
  });
  const updateRow = useMutation({
    mutationFn: ({ rowId, input }: { rowId: number; input: Record<string, string | boolean | null> }) =>
      patchImportRow(batchId as number, rowId, input),
    onSuccess: () => {
      setEditing(undefined);
      void queryClient.invalidateQueries({ queryKey: ["import-batch", batchId] });
      void queryClient.invalidateQueries({ queryKey: ["import-rows", batchId] });
    },
  });
  const commit = useMutation({
    mutationFn: (strategy: "all" | "resolved_only") => commitImportBatch(batchId as number, strategy),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["import-batch", batchId] });
      void queryClient.invalidateQueries({ queryKey: ["import-rows", batchId] });
      void queryClient.invalidateQueries({ queryKey: ["journeys"] });
    },
  });

  return (
    <section className="simple-page" aria-labelledby="csv-title">
      <header className="page-heading page-heading--with-action">
        <div>
          <h1 id="csv-title">CSV 导入</h1>
          <p>逐行检查匹配结果，歧义不会被静默提交。</p>
        </div>
        <div className="header-actions">
          <a className="button button--secondary" download href="/api/v1/import-batches/template.csv">下载模板</a>
          <input
            accept=".csv,text/csv"
            className="sr-only"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) upload.mutate(file);
            }}
            ref={inputRef}
            type="file"
          />
          <button className="button button--primary" disabled={upload.isPending} onClick={() => inputRef.current?.click()} type="button">
            {upload.isPending ? "正在解析" : "选择 CSV 文件"}
          </button>
        </div>
      </header>
      {upload.isError ? <p className="form-message form-message--error" role="alert">文件无法解析，请确认编码、列名与大小。</p> : null}
      {batch.data ? (
        <div className="batch-summary" aria-live="polite">
          <strong>{batch.data.filename}</strong>
          <span>{batch.data.total_rows} 行</span>
          <span>{batch.data.resolved_rows} 已解析</span>
          <span>{batch.data.review_rows} 待确认</span>
          <span>{batch.data.failed_rows} 未解析</span>
        </div>
      ) : null}
      {batch.data?.status === "committed" ? (
        <p className="form-message form-message--success" role="status">
          已事务提交 {batch.data.resolved_rows} 个分段；相同 journey_id 已合并为一条多段行程。
        </p>
      ) : null}
      {batchId ? (
        <>
          <div className="review-toolbar" aria-label="审核筛选">
            <label>状态
              <select
                onChange={(event) => {
                  setStatus(event.target.value);
                  setPage(0);
                }}
                value={status}
              >
                <option value="">全部</option>
                <option value="resolved">已解析</option>
                <option value="needs_review">需确认</option>
                <option value="unresolved">未解析</option>
                <option value="ignored">已忽略</option>
                <option value="committed">已提交</option>
              </select>
            </label>
            <button
              className="button button--primary"
              disabled={!batch.data?.resolved_rows || commit.isPending || batch.data.status === "committed"}
              onClick={() => commit.mutate("all")}
              type="button"
            >
              {batch.data?.status === "committed" ? "已提交" : "提交全部已审核行"}
            </button>
          </div>
          {commit.isError ? (
            <div className="commit-warning" role="alert">
              仍有问题行。请修复、选择候选或忽略；也可以明确只提交已解析行。
              <button className="button button--secondary" onClick={() => commit.mutate("resolved_only")} type="button">只提交已解析行</button>
            </div>
          ) : null}
          <div className="table-scroll" tabIndex={0} aria-label="CSV 行审核表格，可横向滚动">
            <table className="review-table">
              <thead><tr>{["行", "行程", "方式", "城市 / 车次", "线路 / 提示", "起点", "终点", "状态", "操作"].map((header) => <th key={header}>{header}</th>)}</tr></thead>
              <tbody>
                {rows.data?.items.map((row) => (
                  <tr key={row.id} data-status={row.resolution_status === "needs_review" ? "review" : row.resolution_status}>
                    <td>{row.row_no}</td>
                    <td>{row.normalized.journey_id || "单行"}</td>
                    <td>{row.normalized.mode === "rail" ? "铁路" : "地铁"}</td>
                    <td>{row.normalized.mode === "rail" ? (row.normalized.train_no || row.normalized.train_type) : row.normalized.city}</td>
                    <td>{row.normalized.mode === "rail" ? row.normalized.route_hint : row.normalized.line}</td>
                    <td>{row.normalized.from_station}</td>
                    <td>{row.normalized.to_station}</td>
                    <td>
                      <span className={`status-text status-text--${row.resolution_status === "needs_review" ? "review" : row.resolution_status}`}>
                        {statusLabels[row.resolution_status] ?? row.resolution_status}
                      </span>
                      {row.error_message ? <small>{row.error_message}</small> : null}
                    </td>
                    <td className="table-actions">
                      {row.resolution_status === "needs_review" && batch.data?.status !== "committed" ? (
                        <select
                          aria-label={`第 ${row.row_no} 行候选`}
                          onChange={(event) => updateRow.mutate({ rowId: row.id, input: { selected_candidate_id: event.target.value } })}
                          value={row.selected_candidate_id ?? ""}
                        >
                          <option value="">选择候选</option>
                          {row.candidates.map((candidate) => (
                            <option key={candidate.candidate_id} value={candidate.candidate_id}>
                              {candidate.mode === "rail" ? candidate.routing_profile : candidate.direction_name} · {(candidate.distance_m / 1000).toFixed(1)} km
                            </option>
                          ))}
                        </select>
                      ) : null}
                      {batch.data?.status !== "committed" ? (
                        <>
                          <button className="button button--secondary" onClick={() => setEditing(row)} type="button">修复</button>
                          <button className="button button--secondary" onClick={() => updateRow.mutate({ rowId: row.id, input: { ignored: true } })} type="button">忽略</button>
                        </>
                      ) : <span>不可修改</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {rows.data ? (
            <nav className="table-pagination" aria-label="CSV 审核分页">
              <span>
                {rows.data.total === 0
                  ? "没有符合条件的行"
                  : `第 ${page * PAGE_SIZE + 1}–${Math.min((page + 1) * PAGE_SIZE, rows.data.total)} 行，共 ${rows.data.total} 行`}
              </span>
              <div>
                <button
                  className="button button--secondary button--compact"
                  disabled={page === 0 || rows.isFetching}
                  onClick={() => setPage((current) => Math.max(0, current - 1))}
                  type="button"
                >
                  上一页
                </button>
                <button
                  className="button button--secondary button--compact"
                  disabled={(page + 1) * PAGE_SIZE >= rows.data.total || rows.isFetching}
                  onClick={() => setPage((current) => current + 1)}
                  type="button"
                >
                  下一页
                </button>
              </div>
            </nav>
          ) : null}
        </>
      ) : (
        <div className="empty-state"><h2>选择一个 CSV 文件</h2><p>支持 UTF-8 / UTF-8-SIG，最多 5 MB、10,000 行。</p></div>
      )}
      {editing && batch.data?.status !== "committed" ? (
        <ModalDialog
          className="row-editor"
          labelledBy="csv-row-editor-title"
          onClose={() => setEditing(undefined)}
        >
          <form
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              updateRow.mutate({
                rowId: editing.id,
                input: Object.fromEntries(
                  (editing.normalized.mode === "rail" ? RAIL_REPAIR_FIELDS : METRO_REPAIR_FIELDS).map((key) => {
                    const value = form.get(key);
                    return [key, typeof value === "string" ? value : ""];
                  }),
                ),
              });
            }}
          >
            <h2 id="csv-row-editor-title">修复第 {editing.row_no} 行</h2>
            {(editing.normalized.mode === "rail" ? RAIL_REPAIR_FIELDS : METRO_REPAIR_FIELDS).map((field, index) => (
              <label className="field" key={field}><span className="field__label">{field}</span><input autoFocus={index === 0} defaultValue={editing.normalized[field] ?? ""} name={field} /></label>
            ))}
            <div className="row-editor__actions">
              <button className="button button--secondary" onClick={() => setEditing(undefined)} type="button">取消</button>
              <button className="button button--primary" disabled={updateRow.isPending} type="submit">重新解析</button>
            </div>
          </form>
        </ModalDialog>
      ) : null}
    </section>
  );
}
