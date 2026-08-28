import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import {
  downloadGpx,
  previewExport,
  searchRailStations,
  type CreateJourneyInput,
  type ExportOptions,
  type RailPathCandidate,
  type RailStation,
  type RailTrainType,
  type RequestError,
} from "../../api/client";
import { Icon } from "../../components/Icon";
import { downloadBlob } from "../../utils/download";
import { JourneyModeTabs } from "./JourneyModeTabs";
import { RailPreviewMap } from "./RailPreviewMap";
import { RailStationCombobox } from "./RailStationCombobox";
import {
  useCreateJourney,
  useRailDataStatus,
  useRailPathPreview,
} from "./useJourneyNetwork";
import { usePublicConfig } from "./usePublicConfig";

type RailJourneyEditorPageProps = {
  onModeChange: (mode: "metro" | "rail") => void;
};

const TRAIN_TYPES: { value: RailTrainType; label: string }[] = [
  { value: "G", label: "G · 高速动车" },
  { value: "C", label: "C · 城际动车" },
  { value: "D", label: "D · 动车" },
  { value: "S", label: "S · 市域列车" },
  { value: "Z", label: "Z · 直达特快" },
  { value: "T", label: "T · 特快" },
  { value: "K", label: "K · 快速" },
  { value: "Y", label: "Y · 旅游列车" },
  { value: "OTHER", label: "其他 / 无字头" },
];

const PROFILE_LABELS: Record<string, string> = {
  china_high_speed: "高速铁路优先",
  china_emu: "动车线路优先",
  china_conventional: "普速铁路优先",
};
const EMPTY_RAIL_CANDIDATES: RailPathCandidate[] = [];

function errorMessage(error: unknown, fallback: string) {
  return (error as RequestError | undefined)?.message || fallback;
}

function warningMessage(warning: Record<string, unknown>) {
  return typeof warning.message === "string"
    ? warning.message
    : typeof warning.code === "string"
      ? warning.code
      : "候选包含需要人工核对的信息。";
}

const SCORE_LABELS: Record<string, string> = {
  train_profile_preference: "车次与路由 Profile",
  ordered_stations: "有序站序覆盖",
  train_compatibility: "动车组与线路属性",
  mainline_ratio: "铁路正线占比",
  railway_class: "国铁轨道占比",
  osm_route_relation: "OSM route 关系",
  distance_rationality: "距离合理性",
};

function percentage(value: unknown) {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "数据不足";
}

function railUnavailableMessage({
  isError,
  isPending,
  status,
  errorMessage: backendMessage,
}: {
  isError: boolean;
  isPending: boolean;
  status?: string;
  errorMessage?: string | null;
}) {
  if (isPending) return "正在检查铁路图与车站索引，请稍候。";
  if (isError) return "无法读取铁路服务状态，请确认本地服务正在运行后重新检查。";
  if (backendMessage) return backendMessage;
  if (status === "disabled") return "当前本地服务未启用铁路功能；乘车事实仍可填写，车站搜索和路径预览暂不可用。";
  if (status === "importing") return "铁路车站索引正在构建；乘车事实仍可填写，完成后即可搜索车站。";
  if (status === "unavailable") return "铁路路由服务当前未连接；乘车事实仍可填写，请启动 sidecar 后重新检查。";
  if (status === "version_mismatch") return "铁路图、车站索引或 sidecar 版本不一致，请在数据设置中核对版本。";
  return "铁路图或车站索引尚未配置；乘车事实仍可填写。";
}

function scoreDetailMessage(detail: Record<string, unknown>) {
  const code = typeof detail.code === "string" ? detail.code : "unknown";
  if (code === "osm_route_relation" && detail.status === "not_exposed_by_sidecar") {
    return "sidecar 尚未暴露该关系，本项不计分，线路提示仅供人工核对";
  }
  if (code === "train_compatibility") {
    return `得分 ${percentage(detail.score)} · 速度属性覆盖 ${percentage(detail.speed_coverage)} · 匹配区段 ${percentage(detail.speed_ratio)}`;
  }
  if (code === "mainline_ratio") {
    return `得分 ${percentage(detail.score)} · 正线 ${percentage(detail.ratio)} · 属性覆盖 ${percentage(detail.coverage)}`;
  }
  if (code === "railway_class") {
    return `得分 ${percentage(detail.score)} · 国铁轨道 ${percentage(detail.rail_ratio)}`;
  }
  if (code === "distance_rationality") {
    const ratio = typeof detail.route_to_direct_ratio === "number" ? detail.route_to_direct_ratio.toFixed(2) : "未知";
    return `得分 ${percentage(detail.score)} · 路径/站间直线距离 ${ratio} 倍`;
  }
  return `得分 ${percentage(detail.score)}`;
}

export function RailJourneyEditorPage({ onModeChange }: RailJourneyEditorPageProps) {
  const [travelDate, setTravelDate] = useState("");
  const [trainNo, setTrainNo] = useState("");
  const [trainType, setTrainType] = useState<RailTrainType>("G");
  const [startStation, setStartStation] = useState<RailStation>();
  const [endStation, setEndStation] = useState<RailStation>();
  const [viaPicker, setViaPicker] = useState<RailStation>();
  const [viaStations, setViaStations] = useState<RailStation[]>([]);
  const [pastedStops, setPastedStops] = useState("");
  const [pasteError, setPasteError] = useState<string>();
  const [isResolvingPaste, setIsResolvingPaste] = useState(false);
  const [routeHint, setRouteHint] = useState("");
  const [note, setNote] = useState("");
  const [selectedCandidateId, setSelectedCandidateId] = useState<string>();
  const [savedJourneyId, setSavedJourneyId] = useState<number>();
  const candidateTitleRef = useRef<HTMLHeadingElement>(null);
  const railStatus = useRailDataStatus();
  const pathPreview = useRailPathPreview();
  const createJourney = useCreateJourney();
  const publicConfig = usePublicConfig();
  const directExport = useMutation({
    mutationFn: async (journeyId: number) => {
      const options: ExportOptions = {
        mode: "journeys",
        max_segment_length_m: 25,
        rail_max_segment_length_m: 200,
        journey_ids: [journeyId],
      };
      const exportPreview = await previewExport(options);
      if (exportPreview.blocking_errors.length > 0) {
        throw new Error(exportPreview.blocking_errors.join("；"));
      }
      return downloadGpx({ ...options, preview_token: exportPreview.preview_token });
    },
    onSuccess: ({ blob, filename }) => downloadBlob(blob, filename),
  });
  const candidates = pathPreview.data?.candidates ?? EMPTY_RAIL_CANDIDATES;
  const selectedCandidate = useMemo<RailPathCandidate | undefined>(
    () =>
      candidates.find((candidate) => candidate.candidate_id === selectedCandidateId) ??
      candidates[0],
    [candidates, selectedCandidateId],
  );
  const orderedStations = useMemo(
    () => [startStation, ...viaStations, endStation].filter((station): station is RailStation => Boolean(station)),
    [endStation, startStation, viaStations],
  );
  const railReady = railStatus.data?.status === "ready";
  const unavailableMessage = railReady
    ? undefined
    : railUnavailableMessage({
        isError: railStatus.isError,
        isPending: railStatus.isPending,
        status: railStatus.data?.status,
        errorMessage: railStatus.data?.error_message,
      });
  const statusMessage = railStatus.isPending
    ? "正在检查铁路图状态"
    : railStatus.isError
      ? "铁路图状态读取失败"
      : railReady
        ? undefined
        : (railStatus.data?.error_message ?? "铁路图尚未就绪");
  const canPreview = Boolean(
    railReady &&
      travelDate &&
      startStation &&
      endStation &&
      startStation.id !== endStation.id &&
      !pathPreview.isPending,
  );

  useEffect(() => {
    if (selectedCandidate) candidateTitleRef.current?.focus();
  }, [selectedCandidate]);

  function resetCandidate() {
    setSelectedCandidateId(undefined);
    setSavedJourneyId(undefined);
    pathPreview.reset();
    createJourney.reset();
    directExport.reset();
  }

  function addViaStation(station: RailStation) {
    const usedIds = new Set([
      startStation?.id,
      endStation?.id,
      ...viaStations.map((item) => item.id),
    ]);
    if (usedIds.has(station.id)) {
      setPasteError(`${station.name_cn} 已经在站序中。`);
      return;
    }
    setViaStations((current) => [...current, station]);
    setViaPicker(undefined);
    setPasteError(undefined);
    resetCandidate();
  }

  async function resolvePastedStops() {
    const names = pastedStops
      .split(/[\n|]+/)
      .map((name) => name.trim())
      .filter(Boolean);
    if (!names.length) {
      setPasteError("请先粘贴至少一个途经站名。");
      return;
    }
    if (names.length > 30) {
      setPasteError("一次最多解析 30 个途经站。");
      return;
    }
    setIsResolvingPaste(true);
    setPasteError(undefined);
    try {
      const resultSets = await Promise.all(
        names.map((query) => searchRailStations({ query })),
      );
      const resolved = resultSets.map((matches, index) => {
        const exactMatches = matches.filter((station) => station.match_score === 100);
        if (exactMatches.length !== 1) {
          throw new Error(
            exactMatches.length > 1
              ? `${names[index]} 匹配到多个车站，请使用上方搜索逐个确认。`
              : `${names[index]} 没有唯一精确匹配，请使用上方搜索逐个确认。`,
          );
        }
        return exactMatches[0];
      });
      const allIds = [startStation?.id, endStation?.id, ...resolved.map((station) => station.id)];
      if (new Set(allIds).size !== allIds.length) {
        throw new Error("粘贴的站序包含重复站点或与起终点重复。");
      }
      setViaStations(resolved);
      setPastedStops("");
      resetCandidate();
    } catch (error) {
      setPasteError(errorMessage(error, "站序解析失败。"));
    } finally {
      setIsResolvingPaste(false);
    }
  }

  function previewRailJourney() {
    if (!canPreview || !startStation || !endStation) return;
    pathPreview.mutate(
      {
        mode: "rail",
        travel_date: travelDate,
        train_no: trainNo.trim() || null,
        train_type: trainType,
        start_station_id: startStation.id,
        end_station_id: endStation.id,
        via_station_ids: viaStations.map((station) => station.id),
        route_hint: routeHint.trim() || null,
      },
      {
        onSuccess: (preview) => {
          setSelectedCandidateId(preview.candidates[0]?.candidate_id);
        },
      },
    );
  }

  function buildJourneyInput(): CreateJourneyInput | undefined {
    if (!selectedCandidate?.can_commit || !startStation || !endStation) return undefined;
    return {
      traveled_at: travelDate,
      note: note.trim() || null,
      source_type: "manual",
      legs: [
        {
          mode: "rail",
          travel_date: travelDate,
          train_no: trainNo.trim() || null,
          train_type: trainType,
          start_station_id: startStation.id,
          end_station_id: endStation.id,
          via_station_ids: viaStations.map((station) => station.id),
          route_hint: routeHint.trim() || null,
          candidate_id: selectedCandidate.candidate_id,
          candidate_digest: selectedCandidate.digest,
        },
      ],
    };
  }

  function saveJourney() {
    const input = buildJourneyInput();
    if (!input) return;
    createJourney.mutate(input, {
      onSuccess: (journey) => setSavedJourneyId(journey.id),
    });
  }

  async function exportJourney() {
    try {
      let journeyId = savedJourneyId;
      if (journeyId === undefined) {
        const input = buildJourneyInput();
        if (!input) return;
        const journey = await createJourney.mutateAsync(input);
        journeyId = journey.id;
        setSavedJourneyId(journey.id);
      }
      await directExport.mutateAsync(journeyId);
    } catch {
      // Mutation state is rendered beside the candidate actions.
    }
  }

  return (
    <section className="journey-editor journey-editor--rail" aria-labelledby="rail-journey-editor-title">
      <div className="journey-workspace journey-workspace--rail">
        <form
          className="journey-form"
          onSubmit={(event) => {
            event.preventDefault();
            previewRailJourney();
          }}
        >
          <h1 id="rail-journey-editor-title">添加一段真实铁路乘坐记录</h1>
          <JourneyModeTabs mode="rail" onChange={onModeChange} />
          {!railReady ? (
            <aside className="rail-readiness" aria-live="polite">
              <div>
                <strong>铁路功能暂不可用</strong>
                <span>{unavailableMessage}</span>
              </div>
              <div className="rail-readiness__actions">
                <button
                  className="button button--secondary button--compact"
                  disabled={railStatus.isFetching}
                  onClick={() => void railStatus.refetch()}
                  type="button"
                >
                  {railStatus.isFetching ? "正在检查" : "重新检查"}
                </button>
                <Link className="button button--secondary button--compact" to="/settings/data">
                  查看铁路设置
                </Link>
              </div>
            </aside>
          ) : null}
          <label className="field">
            <span className="field__label">乘坐日期（必填）</span>
            <input
              onChange={(event) => {
                setTravelDate(event.target.value);
                resetCandidate();
              }}
              required
              type="date"
              value={travelDate}
            />
          </label>
          <div className="rail-train-row">
            <label className="field">
              <span className="field__label">车次（建议）</span>
              <input
                maxLength={80}
                onChange={(event) => {
                  setTrainNo(event.target.value);
                  resetCandidate();
                }}
                placeholder="例如 G1"
                value={trainNo}
              />
            </label>
            <label className="field">
              <span className="field__label">车型</span>
              <select
                onChange={(event) => {
                  setTrainType(event.target.value as RailTrainType);
                  resetCandidate();
                }}
                value={trainType}
              >
                {TRAIN_TYPES.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
              </select>
            </label>
          </div>
          <RailStationCombobox
            label="上车站"
            name="railStartStation"
            onSelect={(station) => {
              setStartStation(station);
              resetCandidate();
            }}
            searchEnabled={railReady}
            unavailableMessage={unavailableMessage}
            value={startStation}
          />
          <RailStationCombobox
            label="下车站"
            name="railEndStation"
            onSelect={(station) => {
              setEndStation(station);
              resetCandidate();
            }}
            searchEnabled={railReady}
            unavailableMessage={unavailableMessage}
            value={endStation}
          />
          <div className="rail-via-editor">
            <RailStationCombobox
              disabled={viaStations.length >= 30}
              label="添加途经站（可选）"
              name="railViaStation"
              onSelect={addViaStation}
              searchEnabled={railReady}
              unavailableMessage={unavailableMessage}
              value={viaPicker}
            />
            {viaStations.length ? (
              <ol className="rail-stop-sequence" aria-label="已锁定途经站顺序">
                {viaStations.map((station, index) => (
                  <li key={station.id}>
                    <span><strong>{index + 1}</strong>{station.name_cn}<small>已锁定</small></span>
                    <span className="rail-stop-sequence__actions">
                      <button
                        aria-label={`上移 ${station.name_cn}`}
                        disabled={index === 0}
                        onClick={() => {
                          setViaStations((current) => {
                            const next = [...current];
                            [next[index - 1], next[index]] = [next[index], next[index - 1]];
                            return next;
                          });
                          resetCandidate();
                        }}
                        type="button"
                      >上移</button>
                      <button
                        aria-label={`下移 ${station.name_cn}`}
                        disabled={index === viaStations.length - 1}
                        onClick={() => {
                          setViaStations((current) => {
                            const next = [...current];
                            [next[index], next[index + 1]] = [next[index + 1], next[index]];
                            return next;
                          });
                          resetCandidate();
                        }}
                        type="button"
                      >下移</button>
                      <button
                        aria-label={`删除 ${station.name_cn}`}
                        onClick={() => {
                          setViaStations((current) => current.filter((item) => item.id !== station.id));
                          resetCandidate();
                        }}
                        type="button"
                      >删除</button>
                    </span>
                  </li>
                ))}
              </ol>
            ) : null}
            <details className="rail-paste-stops">
              <summary>粘贴多行途经站</summary>
              <textarea
                onChange={(event) => setPastedStops(event.target.value)}
                placeholder={"每行一个站名，或用 | 分隔\n例如：嘉兴南\n桐乡"}
                rows={3}
                value={pastedStops}
              />
              <button
                className="button button--secondary button--compact"
                disabled={!railReady || !pastedStops.trim() || isResolvingPaste}
                onClick={() => void resolvePastedStops()}
                type="button"
              >
                {isResolvingPaste ? "正在解析" : "解析并锁定站序"}
              </button>
            </details>
          </div>
          {pasteError ? <p className="form-message form-message--error" role="alert">{pasteError}</p> : null}
          <label className="field">
            <span className="field__label">线路提示（可选）</span>
            <input
              maxLength={500}
              onChange={(event) => {
                setRouteHint(event.target.value);
                resetCandidate();
              }}
              placeholder="例如 沪昆高速铁路"
              value={routeHint}
            />
          </label>
          <label className="field">
            <span className="field__label">备注（可选）</span>
            <textarea
              maxLength={2000}
              onChange={(event) => setNote(event.target.value)}
              placeholder="可填写座次或核对信息"
              rows={2}
              value={note}
            />
          </label>
          <button className="button button--primary button--full" disabled={!canPreview} type="submit">
            <Icon name="eye" size={18} />
            {!railReady
              ? "铁路数据就绪后可预览"
              : pathPreview.isPending
                ? "正在计算铁路候选"
                : "预览铁路路径"}
          </button>
        </form>
        <div className="map-stage">
          <RailPreviewMap
            candidates={candidates}
            onSelectCandidate={(candidateId) => {
              setSelectedCandidateId(candidateId);
              setSavedJourneyId(undefined);
            }}
            selectedCandidateId={selectedCandidate?.candidate_id}
            stations={orderedStations}
            statusMessage={statusMessage}
            tiles={
              publicConfig.data
                ? {
                    enabled: publicConfig.data.map.tiles_enabled,
                    url: publicConfig.data.map.tile_url,
                    attribution: publicConfig.data.map.tile_attribution,
                    maxZoom: publicConfig.data.map.max_zoom,
                  }
                : undefined
            }
          />
        </div>
      </div>
      {!selectedCandidate ? (
        <div className="candidate-rail candidate-rail--idle" aria-live="polite">
          <p>
            {pathPreview.isError
              ? errorMessage(pathPreview.error, "铁路路径计算失败，请核对图版本和有序站点。")
              : pathPreview.data?.status === "unresolved"
                ? "没有找到通过全部有序站点的铁路路径。"
                : "填写乘车事实后预览，最多返回 3 条可解释候选。"}
          </p>
        </div>
      ) : (
        <section className="candidate-rail candidate-rail--rail" aria-labelledby="rail-candidate-title">
          <div className="candidate-rail__title">
            <h2 id="rail-candidate-title" ref={candidateTitleRef} tabIndex={-1}>铁路候选</h2>
            <strong>{startStation?.name_cn} → {endStation?.name_cn}</strong>
            {candidates.length > 1 ? (
              <select
                aria-label="铁路候选路径"
                onChange={(event) => {
                  setSelectedCandidateId(event.target.value);
                  setSavedJourneyId(undefined);
                }}
                value={selectedCandidate.candidate_id}
              >
                {candidates.map((candidate, index) => (
                  <option key={candidate.candidate_id} value={candidate.candidate_id}>
                    候选 {index + 1} · {PROFILE_LABELS[candidate.routing_profile] ?? candidate.routing_profile}
                  </option>
                ))}
              </select>
            ) : null}
          </div>
          <dl className="candidate-rail__facts">
            <div><dt>距离</dt><dd><Icon name="ruler" size={17} />{(selectedCandidate.distance_m / 1000).toFixed(1)} km</dd></div>
            <div><dt>置信度</dt><dd>{Math.round(selectedCandidate.score * 100)}%</dd></div>
            <div><dt>来源区间</dt><dd>{selectedCandidate.way_ranges.length} 个 OSM way</dd></div>
          </dl>
          <div className="candidate-rail__actions">
            <button className="button button--secondary" onClick={resetCandidate} type="button">返回修改</button>
            <button
              className="button button--primary candidate-rail__export"
              disabled={!selectedCandidate.can_commit || createJourney.isPending || directExport.isPending}
              onClick={() => void exportJourney()}
              type="button"
            >
              <Icon name="download" size={17} />
              {directExport.isPending ? "正在导出" : savedJourneyId ? "导出 GPX" : "保存并导出"}
            </button>
            <button
              className="button button--secondary"
              disabled={!selectedCandidate.can_commit || savedJourneyId !== undefined || createJourney.isPending}
              onClick={saveJourney}
              type="button"
            >
              <Icon name="check" size={17} />
              {savedJourneyId ? "已保存" : createJourney.isPending ? "正在保存" : "确认并保存"}
            </button>
          </div>
          <details className="rail-score-details">
            <summary>查看评分依据 · 模型 {selectedCandidate.scoring_version}</summary>
            <ul>
              {selectedCandidate.score_details
                .filter((detail) => detail.code !== "scoring_version")
                .map((detail, index) => (
                  <li key={`${String(detail.code)}-${index}`}>
                    <strong>{SCORE_LABELS[String(detail.code)] ?? String(detail.code)}</strong>
                    <span>{scoreDetailMessage(detail)}</span>
                  </li>
                ))}
            </ul>
          </details>
          {selectedCandidate.warnings.length ? (
            <ul className="rail-candidate-warnings">
              {selectedCandidate.warnings.map((warning, index) => (
                <li key={`${String(warning.code)}-${index}`}>{warningMessage(warning)}</li>
              ))}
            </ul>
          ) : null}
          {createJourney.isError || directExport.isError ? (
            <p className="form-message form-message--error" role="alert">
              {errorMessage(createJourney.error ?? directExport.error, "保存或导出失败，请重新预览候选。")}
            </p>
          ) : null}
        </section>
      )}
      <p className="sr-only" aria-live="polite">{savedJourneyId ? "铁路行程已保存。" : ""}</p>
    </section>
  );
}
