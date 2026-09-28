import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  downloadGpx,
  fetchJourneys,
  fetchJourneyFilters,
  previewExport,
  type ExportOptions,
} from "../../api/client";
import { Pagination } from "../../components/Pagination";
import { downloadBlob } from "../../utils/download";

export function ExportPage() {
  const [mode, setMode] = useState<ExportOptions["mode"]>("coverage");
  const [spacing, setSpacing] = useState<"15" | "25" | "50" | "original">("25");
  const [railSpacing, setRailSpacing] = useState<"100" | "200" | "500" | "original">("200");
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [cityId, setCityId] = useState<number>();
  const [lineId, setLineId] = useState<number>();
  const [traveledFrom, setTraveledFrom] = useState("");
  const [traveledTo, setTraveledTo] = useState("");
  const [scope, setScope] = useState<"all" | "selected">("all");
  const [selectedJourneyIds, setSelectedJourneyIds] = useState<number[]>([]);
  const filters = useQuery({ queryKey: ["journeys", "filters"], queryFn: ({ signal }) => fetchJourneyFilters(signal) });
  const listOptions = { q: search, limit: 50, offset: page * 50, city_id: cityId, line_id: lineId, traveled_from: traveledFrom, traveled_to: traveledTo };
  const journeys = useQuery({
    queryKey: ["journeys", "selection", listOptions],
    queryFn: ({ signal }) => fetchJourneys({ ...listOptions, signal }),
    enabled: scope === "selected",
  });
  const cities = filters.data?.cities ?? [];
  const lines = (filters.data?.lines ?? []).filter((line) => cityId === undefined || line.city_id === cityId);
  function resetSelection() { setPage(0); setSelectedJourneyIds([]); }
  const options = useMemo<ExportOptions>(
    () => ({
      mode,
      max_segment_length_m:
        spacing === "original" ? null : (Number(spacing) as 15 | 25 | 50),
      rail_max_segment_length_m:
        railSpacing === "original" ? null : (Number(railSpacing) as 100 | 200 | 500),
      journey_ids: scope === "selected" ? selectedJourneyIds : [],
      city_id: cityId ?? null,
      line_id: lineId ?? null,
      traveled_from: traveledFrom || null,
      traveled_to: traveledTo || null,
    }),
    [cityId, lineId, mode, railSpacing, scope, selectedJourneyIds, spacing, traveledFrom, traveledTo],
  );
  const validRange = !(traveledFrom && traveledTo && traveledFrom > traveledTo);
  const previewQuery = useQuery({
    queryKey: ["journeys", "export-preview", options],
    queryFn: ({ signal }) => previewExport(options, signal),
    enabled: validRange && (scope === "all" || selectedJourneyIds.length > 0),
  });
  const preview = validRange && (scope === "all" || selectedJourneyIds.length > 0) ? previewQuery.data : undefined;
  const downloadMutation = useMutation({
    mutationFn: downloadGpx,
    onSuccess: ({ blob, filename }) => downloadBlob(blob, filename),
  });
  const blocked = !preview || previewQuery.isFetching || previewQuery.isError ||
    preview.blocking_errors.length > 0 ||
    (scope === "selected" && selectedJourneyIds.length === 0) || !validRange;

  return (
    <section className="simple-page export-page" aria-labelledby="export-title">
      <header className="page-heading">
        <h1 id="export-title">导出</h1>
        <p>导出前检查范围、去重方式与轨迹点间距。</p>
      </header>
      <div className="export-layout">
        <fieldset className="choice-group">
          <legend>导出模式</legend>
          <label><input checked={mode === "journeys"} onChange={() => setMode("journeys")} type="radio" />行程模式（保留每次行程）</label>
          <label><input checked={mode === "coverage"} onChange={() => setMode("coverage")} type="radio" />区间去重（合并重复区间）</label>
        </fieldset>
        <dl className="summary-list" aria-live="polite">
          <div><dt>行程</dt><dd>{preview?.journey_count ?? 0} 条</dd></div>
          <div><dt>区间</dt><dd>{preview?.edge_count ?? 0} 段</dd></div>
          <div><dt>去重后区间</dt><dd>{preview?.unique_edge_count ?? 0} 段</dd></div>
          <div><dt>总距离</dt><dd>{((preview?.distance_m ?? 0) / 1000).toFixed(1)} km</dd></div>
          <div><dt>地铁数据版本</dt><dd>{preview?.dataset_version_ids.join(", ") || "无"}</dd></div>
          <div><dt>铁路图版本</dt><dd>{preview?.rail_graph_versions.join(", ") || "无"}</dd></div>
        </dl>
      </div>
      {filters.isError ? <p role="alert">导出筛选项读取失败。<button type="button" onClick={() => void filters.refetch()}>重试</button></p> : null}
      {previewQuery.isFetching ? <p role="status">正在校验导出范围…</p> : null}
      <fieldset className="export-filters">
        <legend>导出范围</legend>
        <label>城市
          <select
            onChange={(event) => {
              setCityId(event.target.value ? Number(event.target.value) : undefined);
              setLineId(undefined);
              resetSelection();
            }}
            value={cityId ?? ""}
          >
            <option value="">全部城市</option>
            {cities.map(({ id, name }) => <option key={id} value={id}>{name}</option>)}
          </select>
        </label>
        <label>线路
          <select onChange={(event) => { setLineId(event.target.value ? Number(event.target.value) : undefined); resetSelection(); }} value={lineId ?? ""}>
            <option value="">全部线路</option>
            {lines.map(({ id, name }) => <option key={id} value={id}>{name}</option>)}
          </select>
        </label>
        <label>起始日期<input onChange={(event) => { setTraveledFrom(event.target.value); resetSelection(); }} type="date" value={traveledFrom} /></label>
        <label>结束日期<input onChange={(event) => { setTraveledTo(event.target.value); resetSelection(); }} type="date" value={traveledTo} /></label>
      </fieldset>
      <fieldset className="export-selection">
        <legend>行程选择</legend>
        <label><input checked={scope === "all"} onChange={() => setScope("all")} type="radio" />符合范围的全部行程</label>
        <label><input checked={scope === "selected"} onChange={() => setScope("selected")} type="radio" />仅勾选的行程</label>
        {scope === "selected" ? (
          <div>
            <label>搜索行程<input type="search" value={search} onChange={(event) => { setSearch(event.target.value); setPage(0); }} /></label>
            <p role="status">已选择 {selectedJourneyIds.length} 条行程（跨页保留）</p>
            {journeys.isPending ? <p role="status">正在读取行程…</p> : null}
            {journeys.isError ? <p role="alert">行程读取失败。<button type="button" onClick={() => void journeys.refetch()}>重试</button></p> : null}
            <div className="export-selection__list">
            {journeys.data?.items.map((journey) => (
              <label key={journey.id}>
                <input
                  checked={selectedJourneyIds.includes(journey.id)}
                  onChange={(event) =>
                    setSelectedJourneyIds((current) =>
                      event.target.checked
                        ? [...current, journey.id]
                        : current.filter((id) => id !== journey.id),
                    )}
                  type="checkbox"
                />
                {journey.traveled_at ?? "日期未填"} · {journey.journey_code}
              </label>
            ))}
            </div>
            {journeys.data ? <Pagination label="导出行程分页" page={page} pageSize={50} total={journeys.data.total} busy={journeys.isFetching} onChange={setPage} /> : null}
          </div>
        ) : null}
      </fieldset>
      <fieldset className="choice-group choice-group--horizontal">
        <legend>地铁点间距（采样间隔）</legend>
        {(["15", "25", "50", "original"] as const).map((value) => (
          <label key={value}>
            <input checked={spacing === value} onChange={() => setSpacing(value)} type="radio" />
            {value === "original" ? "原始折点" : `${value}m`}
          </label>
        ))}
      </fieldset>
      <fieldset className="choice-group choice-group--horizontal">
        <legend>铁路点间距（采样间隔）</legend>
        {(["100", "200", "500", "original"] as const).map((value) => (
          <label key={value}>
            <input checked={railSpacing === value} onChange={() => setRailSpacing(value)} type="radio" />
            {value === "original" ? "原始折点" : `${value}m`}
          </label>
        ))}
      </fieldset>
      {traveledFrom && traveledTo && traveledFrom > traveledTo ? (
        <p className="form-message form-message--error" role="alert">结束日期不能早于起始日期。</p>
      ) : null}
      {previewQuery.isError || downloadMutation.isError ? (
        <p className="form-message form-message--error" role="alert">导出校验失败，请检查已保存行程。</p>
      ) : null}
      {preview?.blocking_errors.map((error) => (
        <p className="form-message form-message--error" key={error}>{error}</p>
      ))}
      {preview?.warnings.map((warning) => (
        <p className="form-message" key={warning}>{warning}</p>
      ))}
      <button
        className="button button--primary export-page__action"
        disabled={blocked || downloadMutation.isPending}
        onClick={() => {
          if (preview) downloadMutation.mutate({ ...options, preview_token: preview.preview_token });
        }}
        type="button"
      >
        {downloadMutation.isPending ? "正在生成" : "生成 GPX"}
      </button>
    </section>
  );
}
