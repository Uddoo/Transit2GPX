import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  downloadGpx,
  fetchJourneys,
  previewExport,
  type ExportOptions,
  type ExportPreview,
} from "../../api/client";
import { downloadBlob } from "../../utils/download";

export function ExportPage() {
  const [mode, setMode] = useState<ExportOptions["mode"]>("coverage");
  const [spacing, setSpacing] = useState<"15" | "25" | "50" | "original">("25");
  const [railSpacing, setRailSpacing] = useState<"100" | "200" | "500" | "original">("200");
  const [preview, setPreview] = useState<ExportPreview>();
  const [cityId, setCityId] = useState<number>();
  const [lineId, setLineId] = useState<number>();
  const [traveledFrom, setTraveledFrom] = useState("");
  const [traveledTo, setTraveledTo] = useState("");
  const [scope, setScope] = useState<"all" | "selected">("all");
  const [selectedJourneyIds, setSelectedJourneyIds] = useState<number[]>([]);
  const journeys = useQuery({
    queryKey: ["journeys"],
    queryFn: ({ signal }) => fetchJourneys({ limit: 500, signal }),
  });
  const cities = useMemo(
    () =>
      Array.from(
        new Map(
          (journeys.data?.items ?? [])
            .flatMap((journey) => journey.legs)
            .filter((leg) => leg.transport_mode === "metro")
            .map((leg) => [leg.city_id, leg.city_name]),
        ),
      ),
    [journeys.data?.items],
  );
  const lines = useMemo(
    () =>
      Array.from(
        new Map(
          (journeys.data?.items ?? [])
            .flatMap((journey) => journey.legs)
            .filter((leg) => leg.transport_mode === "metro")
            .filter((leg) => cityId === undefined || leg.city_id === cityId)
            .map((leg) => [leg.line_id, leg.line_name]),
        ),
      ),
    [cityId, journeys.data?.items],
  );
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
  const previewMutation = useMutation({
    mutationFn: previewExport,
    onSuccess: setPreview,
  });
  const downloadMutation = useMutation({
    mutationFn: downloadGpx,
    onSuccess: ({ blob, filename }) => downloadBlob(blob, filename),
  });

  useEffect(() => {
    setPreview(undefined);
    previewMutation.mutate(options);
  }, [options]); // eslint-disable-line react-hooks/exhaustive-deps

  const blocked =
    !preview ||
    preview.blocking_errors.length > 0 ||
    (scope === "selected" && selectedJourneyIds.length === 0) ||
    Boolean(traveledFrom && traveledTo && traveledFrom > traveledTo);

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
      <fieldset className="export-filters">
        <legend>导出范围</legend>
        <label>城市
          <select
            onChange={(event) => {
              setCityId(event.target.value ? Number(event.target.value) : undefined);
              setLineId(undefined);
            }}
            value={cityId ?? ""}
          >
            <option value="">全部城市</option>
            {cities.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        </label>
        <label>线路
          <select onChange={(event) => setLineId(event.target.value ? Number(event.target.value) : undefined)} value={lineId ?? ""}>
            <option value="">全部线路</option>
            {lines.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        </label>
        <label>起始日期<input onChange={(event) => setTraveledFrom(event.target.value)} type="date" value={traveledFrom} /></label>
        <label>结束日期<input onChange={(event) => setTraveledTo(event.target.value)} type="date" value={traveledTo} /></label>
      </fieldset>
      <fieldset className="export-selection">
        <legend>行程选择</legend>
        <label><input checked={scope === "all"} onChange={() => setScope("all")} type="radio" />符合范围的全部行程</label>
        <label><input checked={scope === "selected"} onChange={() => setScope("selected")} type="radio" />仅勾选的行程</label>
        {scope === "selected" ? (
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
      {previewMutation.isError || downloadMutation.isError ? (
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
