import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import {
  downloadGpx,
  previewExport,
  type CreateJourneyInput,
  type ExportOptions,
  type PathCandidate,
} from "../../api/client";
import { Icon } from "../../components/Icon";
import { downloadBlob } from "../../utils/download";
import { JourneyModeTabs } from "./JourneyModeTabs";
import { RailJourneyEditorPage } from "./RailJourneyEditorPage";
import { useDataStatus } from "../data-settings/useDataStatus";
import { StationCombobox } from "./StationCombobox";
import { TransitPreviewMap } from "./TransitPreviewMap";
import { useCityMap } from "./useCityMap";
import {
  useCities,
  useCreateJourney,
  useLines,
  usePathPreview,
  useStations,
} from "./useJourneyNetwork";
import { usePublicConfig } from "./usePublicConfig";
import { sortTransitLines } from "./lineSort";

type CandidateState = "editing" | "preview" | "saved";

export function JourneyEditorPage() {
  const [mode, setMode] = useState<"metro" | "rail">("metro");
  return mode === "metro" ? (
    <MetroJourneyEditorPage onModeChange={setMode} />
  ) : (
    <RailJourneyEditorPage onModeChange={setMode} />
  );
}

function MetroJourneyEditorPage({
  onModeChange,
}: {
  onModeChange: (mode: "metro" | "rail") => void;
}) {
  const [state, setState] = useState<CandidateState>("editing");
  const [cityId, setCityId] = useState<number>();
  const [lineId, setLineId] = useState<number>();
  const [autoLine, setAutoLine] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [startStationId, setStartStationId] = useState<number>();
  const [endStationId, setEndStationId] = useState<number>();
  const [viaStationId, setViaStationId] = useState<number>();
  const [selectedCandidateId, setSelectedCandidateId] = useState<string>();
  const [traveledAt, setTraveledAt] = useState("");
  const [note, setNote] = useState("");
  const [mapSelection, setMapSelection] = useState<"start" | "end">("start");
  const [usedMapSelection, setUsedMapSelection] = useState(false);
  const [savedJourneyId, setSavedJourneyId] = useState<number>();
  const previewButtonRef = useRef<HTMLButtonElement>(null);
  const candidateTitleRef = useRef<HTMLHeadingElement>(null);
  const dataStatus = useDataStatus();
  const dataReady = Boolean(
    dataStatus.data?.status === "ready" || dataStatus.data?.ready_available,
  );
  const cities = useCities(dataReady);
  const lines = useLines(cityId);
  const sortedLines = useMemo(
    () => (lines.data ? sortTransitLines(lines.data) : []),
    [lines.data],
  );
  const stations = useStations(cityId, lineId, autoLine);
  const pathPreview = usePathPreview();
  const createJourney = useCreateJourney();
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
      return downloadGpx({
        ...options,
        preview_token: exportPreview.preview_token,
      });
    },
    onSuccess: ({ blob, filename }) => downloadBlob(blob, filename),
  });
  const cityMap = useCityMap({
    cityId: cityId ?? 0,
    lineId,
    enabled:
      dataReady && cityId !== undefined && (autoLine || lineId !== undefined),
  });
  const publicConfig = usePublicConfig();

  useEffect(() => {
    if (cities.data?.length && !cities.data.some((city) => city.id === cityId)) {
      setCityId(cities.data[0].id);
    }
  }, [cities.data, cityId]);

  useEffect(() => {
    if (autoLine) return;
    if (
      sortedLines.length &&
      !sortedLines.some((line) => line.id === lineId)
    ) {
      setLineId(sortedLines[0].id);
    }
  }, [autoLine, lineId, sortedLines]);

  useEffect(() => {
    if (!stations.data?.length) {
      return;
    }
    if (!stations.data.some((station) => station.id === startStationId)) {
      setStartStationId(stations.data[0].id);
    }
    if (!stations.data.some((station) => station.id === endStationId)) {
      setEndStationId(stations.data.at(-1)?.id);
    }
  }, [endStationId, startStationId, stations.data]);

  useEffect(() => {
    if (state === "preview") {
      candidateTitleRef.current?.focus();
    }
  }, [state]);

  const selectedCandidate = useMemo<PathCandidate | undefined>(
    () =>
      pathPreview.data?.candidates.find(
        (candidate) => candidate.candidate_id === selectedCandidateId,
      ) ?? pathPreview.data?.candidates[0],
    [pathPreview.data, selectedCandidateId],
  );
  const startStation = stations.data?.find((station) => station.id === startStationId);
  const endStation = stations.data?.find((station) => station.id === endStationId);
  const hasMapFeatures = Boolean(
    cityMap.data &&
      (cityMap.data.lines.features.length > 0 || cityMap.data.stations.features.length > 0),
  );
  const mapState = !dataReady
    ? "unavailable"
    : cityMap.isPending || cities.isPending || lines.isPending || stations.isPending
      ? "loading"
      : cityMap.isError
        ? "error"
        : hasMapFeatures
          ? "ready"
          : "empty";
  const canPreview =
    mapState === "ready" &&
    cityId !== undefined &&
    (autoLine || lineId !== undefined) &&
    startStationId !== undefined &&
    endStationId !== undefined &&
    startStationId !== endStationId &&
    !pathPreview.isPending;

  function resetCandidate() {
    setState("editing");
    setSavedJourneyId(undefined);
    setSelectedCandidateId(undefined);
    pathPreview.reset();
    createJourney.reset();
    directExport.reset();
  }

  function previewSelectedPath() {
    if (!canPreview || !cityId || !startStationId || !endStationId) {
      return;
    }
    pathPreview.mutate(
      {
        city_id: cityId,
        line_id: autoLine ? null : (lineId ?? null),
        start_station_id: startStationId,
        end_station_id: endStationId,
        direction: "auto",
        via_station_ids: viaStationId ? [viaStationId] : [],
      },
      {
        onSuccess: (preview) => {
          setSelectedCandidateId(preview.candidates[0]?.candidate_id);
          setState(preview.candidates.length > 0 ? "preview" : "editing");
        },
      },
    );
  }

  function returnToForm() {
    resetCandidate();
    requestAnimationFrame(() => previewButtonRef.current?.focus());
  }

  function buildJourneyInput(): CreateJourneyInput | undefined {
    if (
      !selectedCandidate ||
      cityId === undefined ||
      startStationId === undefined ||
      endStationId === undefined
    ) {
      return undefined;
    }
    const candidateLegs = selectedCandidate.legs?.length
      ? selectedCandidate.legs.map((leg) => ({
          city_id: cityId,
          line_id: leg.line_id,
          start_station_id: leg.start_station_id,
          end_station_id: leg.end_station_id,
          direction: "auto",
          via_station_ids: [],
          candidate_id: leg.candidate_id,
          candidate_digest: leg.digest,
        }))
      : lineId !== undefined
        ? [
            {
              city_id: cityId,
              line_id: lineId,
              start_station_id: startStationId,
              end_station_id: endStationId,
              direction: "auto",
              via_station_ids: viaStationId ? [viaStationId] : [],
              candidate_id: selectedCandidate.candidate_id,
              candidate_digest: selectedCandidate.digest,
            },
          ]
        : [];
    if (!candidateLegs.length) return undefined;
    return {
      traveled_at: traveledAt || null,
      note: note.trim() || null,
      source_type: usedMapSelection ? "map" : "manual",
      legs: candidateLegs,
    };
  }

  function saveJourney() {
    const input = buildJourneyInput();
    if (!input) return;
    createJourney.mutate(input, {
      onSuccess: (journey) => {
        setSavedJourneyId(journey.id);
        setState("saved");
      },
    });
  }

  async function exportSelectedPath() {
    try {
      let journeyId = savedJourneyId;
      if (journeyId === undefined) {
        const input = buildJourneyInput();
        if (!input) return;
        const journey = await createJourney.mutateAsync(input);
        journeyId = journey.id;
        setSavedJourneyId(journey.id);
        setState("saved");
      }
      await directExport.mutateAsync(journeyId);
    } catch {
      // Mutation state is surfaced next to the candidate actions.
    }
  }

  return (
    <section className="journey-editor journey-editor--metro" aria-labelledby="journey-editor-title">
      <div className="journey-workspace">
        <form
          className="journey-form"
          onSubmit={(event) => {
            event.preventDefault();
            previewSelectedPath();
          }}
        >
          <h1 id="journey-editor-title">添加一段真实乘坐记录</h1>
          <JourneyModeTabs mode="metro" onChange={onModeChange} />
          <div className="journey-form__selectors">
            <label className="field">
              <span className="field__label">城市</span>
              <select
                disabled={!dataReady || !cities.data?.length}
                name="city"
                onChange={(event) => {
                setCityId(Number(event.target.value));
                setAutoLine(false);
                setShowAdvanced(false);
                  setLineId(undefined);
                  setStartStationId(undefined);
                  setEndStationId(undefined);
                  setViaStationId(undefined);
                  resetCandidate();
                }}
                value={cityId ?? ""}
              >
                <option disabled value="">{dataReady ? "选择城市" : "请先导入数据"}</option>
                {cities.data?.map((city) => <option key={city.id} value={city.id}>{city.name_cn}</option>)}
              </select>
            </label>
            <label className="field">
              <span className="field__label">线路</span>
              <select
                disabled={!sortedLines.length}
                name="line"
                onChange={(event) => {
                  const isAuto = event.target.value === "auto";
                  setAutoLine(isAuto);
                  setShowAdvanced(isAuto);
                  setLineId(isAuto ? undefined : Number(event.target.value));
                  setStartStationId(undefined);
                  setEndStationId(undefined);
                  setViaStationId(undefined);
                  resetCandidate();
                }}
                value={autoLine ? "auto" : (lineId ?? "")}
              >
                <option disabled value="">选择线路</option>
                <option value="auto">自动规划换乘（需确认）</option>
                {sortedLines.map((line) => <option key={line.id} value={line.id}>{line.name_cn}</option>)}
              </select>
            </label>
          </div>
          <div className="journey-form__stations">
            <StationCombobox
              cityId={cityId}
              disabled={!stations.data?.length}
              label="起点站"
              lineId={autoLine ? undefined : lineId}
              name="startStation"
              onFocus={() => setMapSelection("start")}
              onSelect={(stationId) => {
                setStartStationId(stationId);
                setUsedMapSelection(false);
                resetCandidate();
              }}
              placeholder="输入站名或拼音"
              stations={stations.data ?? []}
              value={startStationId}
            />
            <StationCombobox
              cityId={cityId}
              disabled={!stations.data?.length}
              label="终点站"
              lineId={autoLine ? undefined : lineId}
              name="endStation"
              onFocus={() => setMapSelection("end")}
              onSelect={(stationId) => {
                setEndStationId(stationId);
                setUsedMapSelection(false);
                resetCandidate();
              }}
              placeholder="输入站名或拼音"
              stations={stations.data ?? []}
              value={endStationId}
            />
          </div>
          <details
            className="journey-form__advanced"
            onToggle={(event) => setShowAdvanced(event.currentTarget.open)}
            open={showAdvanced}
          >
            <summary>更多路线选项</summary>
            <label className="field">
              <span className="field__label">方向（可选）</span>
              <select disabled={!stations.data?.length || autoLine} defaultValue="auto" name="direction">
                <option value="auto">自动识别；歧义时确认</option>
              </select>
            </label>
            <StationCombobox
              clearable
              cityId={cityId}
              disabled={!stations.data?.length}
              emptyLabel="不指定"
              label="途经站（可选）"
              lineId={autoLine ? undefined : lineId}
              name="via"
              onClear={() => {
                setViaStationId(undefined);
                resetCandidate();
              }}
              onSelect={(stationId) => {
                setViaStationId(stationId);
                resetCandidate();
              }}
              placeholder="输入站名或拼音"
              stations={stations.data ?? []}
              value={viaStationId}
            />
          </details>
          <label className="field">
            <span className="field__label">乘坐日期（可选）</span>
            <input
              disabled={!dataReady}
              name="traveledAt"
              onChange={(event) => setTraveledAt(event.target.value)}
              type="date"
              value={traveledAt}
            />
          </label>
          <label className="field">
            <span className="field__label">备注（可选）</span>
            <textarea
              disabled={!dataReady}
              maxLength={200}
              name="note"
              onChange={(event) => setNote(event.target.value)}
              placeholder="可填写备注信息"
              rows={2}
              value={note}
            />
          </label>
          <button
            className="button button--primary button--full"
            disabled={!canPreview}
            ref={previewButtonRef}
            type="submit"
          >
            <Icon name="eye" size={18} />
            {pathPreview.isPending ? "正在解析" : "预览路径"}
          </button>
        </form>

        <div className="map-stage">
          <TransitPreviewMap
            candidateCoordinates={selectedCandidate?.geometry.coordinates}
            data={cityMap.data}
            endStationId={endStationId}
            startStationId={startStationId}
            onStationClick={(stationId) => {
              setUsedMapSelection(true);
              if (mapSelection === "start") {
                setStartStationId(stationId);
                setMapSelection("end");
              } else {
                setEndStationId(stationId);
                setMapSelection("start");
              }
              resetCandidate();
            }}
            state={mapState}
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
          {mapState === "ready" && state === "editing" ? (
            <p className="map-selection-hint" role="status">
              地图点击将设置{mapSelection === "start" ? "起点" : "终点"}；也可使用左侧表单。
            </p>
          ) : null}
        </div>
      </div>
      {state === "editing" || !selectedCandidate ? (
        <div className="candidate-rail candidate-rail--idle" aria-live="polite">
          <p>
            {pathPreview.data?.status === "unresolved"
              ? "没有找到符合条件的真实线路区间。"
              : pathPreview.isError
                ? "路径解析失败，请检查本地数据后重试。"
                : "填写后预览真实线路区间。"}
          </p>
        </div>
      ) : (
        <section className="candidate-rail" aria-labelledby="candidate-title">
          <div className="candidate-rail__title">
            <h2 id="candidate-title" ref={candidateTitleRef} tabIndex={-1}>候选路径</h2>
            <strong>
              {selectedCandidate.line_name} · {startStation?.name_cn} → {endStation?.name_cn}
            </strong>
            {pathPreview.data && pathPreview.data.candidates.length > 1 ? (
              <select
                aria-label="候选方向"
                onChange={(event) => setSelectedCandidateId(event.target.value)}
                value={selectedCandidate.candidate_id}
              >
                {pathPreview.data.candidates.map((candidate) => (
                  <option key={candidate.candidate_id} value={candidate.candidate_id}>
                    {candidate.direction_name} · {(candidate.distance_m / 1000).toFixed(1)} km
                  </option>
                ))}
              </select>
            ) : null}
          </div>
          <dl className="candidate-rail__facts">
            <div><dt>站数</dt><dd><Icon name="train" size={17} />{selectedCandidate.station_count} 站</dd></div>
            <div><dt>距离</dt><dd><Icon name="ruler" size={17} />{(selectedCandidate.distance_m / 1000).toFixed(1)} km</dd></div>
            <div className={selectedCandidate.warnings.length ? "" : "candidate-rail__verified"}>
              <dt>质量</dt><dd><Icon name="check" size={17} />{selectedCandidate.warnings.length ? `${selectedCandidate.warnings.length} 项警告` : "路径已验证，无警告"}</dd>
            </div>
          </dl>
          <div className="candidate-rail__actions">
            <button className="button button--secondary" onClick={returnToForm} type="button">返回修改</button>
            <button
              aria-label="导出 GPX"
              className="button button--primary candidate-rail__export"
              disabled={createJourney.isPending || directExport.isPending}
              onClick={() => void exportSelectedPath()}
              title={
                savedJourneyId === undefined
                  ? "保存当前行程并立即导出 GPX"
                  : "直接导出当前行程的 GPX"
              }
              type="button"
            >
              <Icon name="download" size={17} />
              {directExport.isPending
                ? "正在导出"
                : savedJourneyId === undefined
                  ? "保存并导出"
                  : "导出 GPX"}
            </button>
            <button
              className="button button--secondary"
              disabled={state === "saved" || createJourney.isPending}
              onClick={saveJourney}
              type="button"
            >
              <Icon name="check" size={17} />
              {state === "saved"
                ? "已保存"
                : createJourney.isPending
                  ? "正在保存"
                  : "保存行程"}
            </button>
          </div>
          {createJourney.isError ? (
            <p className="form-message form-message--error" role="alert">
              保存失败，候选可能已过期，请返回重新预览。
            </p>
          ) : null}
          {directExport.isError ? (
            <p className="form-message form-message--error" role="alert">
              GPX 导出失败，请检查当前行程后重试。
            </p>
          ) : null}
        </section>
      )}
      <p className="sr-only" aria-live="polite">
        {state === "saved" ? "行程已保存。" : ""}
      </p>
    </section>
  );
}
