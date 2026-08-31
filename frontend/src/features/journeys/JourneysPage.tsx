import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import {
  confirmRailRecompute,
  deleteJourney,
  fetchJourneys,
  patchJourney,
  previewRailRecompute,
  RequestError,
  reResolveJourney,
  type Journey,
  type RailRecomputeInput,
  type RailRecomputePreview,
} from "../../api/client";
import { ModalDialog } from "../../components/ModalDialog";

function mutationErrorMessage(error: unknown, fallback: string) {
  return error instanceof RequestError ? error.message : fallback;
}

function RailRecomputeDialog({
  journey,
  preview,
  isSaving,
  error,
  onClose,
  onConfirm,
}: {
  journey: Journey;
  preview: RailRecomputePreview;
  isSaving: boolean;
  error: unknown;
  onClose: () => void;
  onConfirm: (input: RailRecomputeInput) => void;
}) {
  const [selectedByLeg, setSelectedByLeg] = useState<Record<number, string>>(() =>
    Object.fromEntries(
      preview.legs.flatMap((leg) => {
        const candidate = leg.candidates.find((item) => item.can_commit);
        return candidate ? [[leg.leg_no, candidate.digest]] : [];
      }),
    ),
  );
  const canConfirm = preview.legs.every((leg) => {
    const selectedDigest = selectedByLeg[leg.leg_no];
    return leg.candidates.some(
      (candidate) => candidate.digest === selectedDigest && candidate.can_commit,
    );
  });

  return (
    <ModalDialog
      className="journey-edit-dialog rail-recompute-dialog"
      labelledBy="rail-recompute-title"
      onClose={onClose}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!canConfirm) return;
          onConfirm({
            target_graph_version: preview.target_graph_version,
            selections: preview.legs.map((leg) => {
              const selected = leg.candidates.find(
                (candidate) => candidate.digest === selectedByLeg[leg.leg_no],
              );
              if (!selected) throw new Error("Missing selected rail candidate");
              return {
                leg_no: leg.leg_no,
                candidate_id: selected.candidate_id,
                candidate_digest: selected.digest,
              };
            }),
          });
        }}
      >
        <header>
          <h2 id="rail-recompute-title">按新铁路图重算</h2>
          <p>
            {journey.journey_code} 将保留不变；确认后创建一条使用
            <strong> {preview.target_graph_version}</strong> 的新行程。
          </p>
        </header>
        <div className="rail-recompute-legs">
          {preview.legs.map((leg) => (
            <fieldset key={leg.leg_no}>
              <legend>
                第 {leg.leg_no} 段 · {leg.station_names.join(" → ")}
              </legend>
              <p className="rail-recompute-version">
                {leg.source_graph_version} → {leg.target_graph_version}
              </p>
              {leg.candidates.length ? (
                <div className="rail-recompute-candidates">
                  {leg.candidates.map((candidate) => (
                    <label
                      className="rail-recompute-candidate"
                      data-selected={
                        selectedByLeg[leg.leg_no] === candidate.digest
                      }
                      key={candidate.digest}
                    >
                      <input
                        checked={selectedByLeg[leg.leg_no] === candidate.digest}
                        disabled={!candidate.can_commit}
                        name={`rail-leg-${leg.leg_no}`}
                        onChange={() =>
                          setSelectedByLeg((current) => ({
                            ...current,
                            [leg.leg_no]: candidate.digest,
                          }))
                        }
                        type="radio"
                        value={candidate.digest}
                      />
                      <span>
                        <strong>{candidate.routing_profile}</strong>
                        <small>
                          {(candidate.distance_m / 1000).toFixed(1)} km · 评分 {Math.round(candidate.score * 100)}%
                        </small>
                        {candidate.warnings.length ? (
                          <small>{candidate.warnings.length} 项需人工留意</small>
                        ) : (
                          <small>无阻断警告</small>
                        )}
                      </span>
                    </label>
                  ))}
                </div>
              ) : (
                <p className="form-message form-message--error" role="alert">
                  该区间没有可确认的候选路径。
                </p>
              )}
            </fieldset>
          ))}
        </div>
        {error ? (
          <p className="form-message form-message--error" role="alert">
            {mutationErrorMessage(error, "重算保存失败，原行程未改变。")}
          </p>
        ) : null}
        <div className="journey-edit-dialog__actions">
          <button className="button button--secondary" onClick={onClose} type="button">
            取消
          </button>
          <button
            className="button button--primary"
            disabled={!canConfirm || isSaving}
            type="submit"
          >
            {isSaving ? "正在创建" : "确认并创建新行程"}
          </button>
        </div>
      </form>
    </ModalDialog>
  );
}

const JOURNEY_PAGE_SIZE = 20;

export function JourneysPage() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(0);
  const [editing, setEditing] = useState<Journey>();
  const [railRecompute, setRailRecompute] = useState<{
    journey: Journey;
    preview: RailRecomputePreview;
  }>();
  const journeys = useQuery({
    queryKey: ["journeys", page],
    queryFn: ({ signal }) =>
      fetchJourneys({
        limit: JOURNEY_PAGE_SIZE,
        offset: page * JOURNEY_PAGE_SIZE,
        signal,
      }),
    placeholderData: (previous) => previous,
  });
  const removeJourney = useMutation({
    mutationFn: deleteJourney,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["journeys"] }),
  });
  const updateJourney = useMutation({
    mutationFn: ({ id, traveledAt, note, expectedUpdatedAt }: { id: number; traveledAt: string | null; note: string | null; expectedUpdatedAt: string }) =>
      patchJourney(id, {
        traveled_at: traveledAt,
        note,
        expected_updated_at: expectedUpdatedAt,
      }),
    onSuccess: () => {
      setEditing(undefined);
      void queryClient.invalidateQueries({ queryKey: ["journeys"] });
    },
  });
  const reResolve = useMutation({
    mutationFn: reResolveJourney,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["journeys"] }),
  });
  const previewRail = useMutation({
    mutationFn: (journey: Journey) => previewRailRecompute(journey.id),
    onSuccess: (preview, journey) => setRailRecompute({ journey, preview }),
  });
  const recomputeRail = useMutation({
    mutationFn: ({ journeyId, input }: { journeyId: number; input: RailRecomputeInput }) =>
      confirmRailRecompute(journeyId, input),
    onSuccess: () => {
      setRailRecompute(undefined);
      void queryClient.invalidateQueries({ queryKey: ["journeys"] });
    },
  });
  const filteredItems = useMemo(() => {
    const key = filter.trim().toLocaleLowerCase();
    if (!key) return journeys.data?.items ?? [];
    return (journeys.data?.items ?? []).filter((journey) =>
      [
        journey.journey_code,
        journey.note ?? "",
        ...journey.legs.flatMap((leg) => [
          leg.city_name ?? "",
          leg.line_name ?? "",
          leg.start_station_name,
          leg.end_station_name,
          leg.transport_mode === "rail" ? (leg.train_no ?? leg.train_type) : "",
        ]),
      ].some((value) => value.toLocaleLowerCase().includes(key)),
    );
  }, [filter, journeys.data?.items]);

  return (
    <section className="simple-page" aria-labelledby="journeys-title">
      <header className="page-heading page-heading--with-action">
        <div>
          <h1 id="journeys-title">行程</h1>
          <p>已确认的地铁乘坐记录会保存在本机。</p>
        </div>
        <Link className="button button--primary" to="/journeys/new">添加行程</Link>
      </header>
      <label className="journey-filter">
        <span className="sr-only">筛选行程</span>
        <input
          onChange={(event) => setFilter(event.target.value)}
          placeholder="按城市、线路、站点、编号或备注筛选"
          type="search"
          value={filter}
        />
        <span>本页 {filteredItems.length} 条</span>
      </label>
      {journeys.isPending ? <p className="panel-message">正在读取行程…</p> : null}
      {journeys.isError ? (
        <div className="panel-message panel-message--error" role="alert">
          <p>行程读取失败。</p>
          <button className="button button--secondary" onClick={() => void journeys.refetch()} type="button">重试</button>
        </div>
      ) : null}
      {journeys.data?.items.length === 0 ? (
        <div className="empty-state">
          <h2>还没有行程</h2>
          <p>选择一段真实乘坐路线，确认后即可保存。</p>
        </div>
      ) : null}
      {journeys.data?.items.length ? (
        <div className="journey-list" aria-label={`共 ${journeys.data.total} 条行程`}>
          {filteredItems.map((journey) => {
            const containsRail = journey.legs.some((leg) => leg.transport_mode === "rail");
            return (
            <article className="journey-card" key={journey.id}>
              <div className="journey-card__main">
                <div className="journey-card__meta">
                  <strong>{journey.traveled_at ?? "日期未填写"}</strong>
                  <span>{journey.journey_code}</span>
                </div>
                <h2>
                  {journey.legs.map((leg) => (
                    <span key={leg.id}>
                      {leg.transport_mode === "rail"
                        ? `铁路 · ${leg.train_no ?? leg.train_type} · ${leg.start_station_name} → ${leg.end_station_name}`
                        : `${leg.city_name} · ${leg.line_name} · ${leg.start_station_name} → ${leg.end_station_name}`}
                    </span>
                  ))}
                </h2>
                <p>
                  {journey.legs.length} 段 · {(journey.distance_m / 1000).toFixed(1)} km
                  {journey.note ? ` · ${journey.note}` : ""}
                </p>
                <details className="journey-card__details">
                  <summary>查看详情</summary>
                  <dl>
                    {journey.legs.map((leg) => (
                      <div key={leg.id}>
                        <dt>第 {leg.leg_no} 段</dt>
                        <dd>
                          {leg.transport_mode === "rail"
                            ? `铁路图 ${leg.graph_version} · ${leg.osm_way_ids.length} 个 OSM way · ${leg.routing_profile}`
                            : `数据版本 ${leg.dataset_version_id} · ${leg.edge_ids.length} 个区间 · ${leg.direction ?? "方向未标注"}`}
                          {" "}· {leg.resolution_status}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </details>
              </div>
              <div className="journey-card__actions">
                <button className="button button--secondary" onClick={() => setEditing(journey)} type="button">编辑</button>
                <button
                  className="button button--secondary"
                  disabled={reResolve.isPending || previewRail.isPending}
                  onClick={() => {
                    if (containsRail) {
                      recomputeRail.reset();
                      previewRail.mutate(journey);
                    } else {
                      reResolve.mutate(journey.id);
                    }
                  }}
                  title={
                    containsRail
                      ? "先预览并确认新候选，再创建新行程；原记录保持不变"
                      : undefined
                  }
                  type="button"
                >
                  {containsRail ? "重算铁路" : "重算"}
                </button>
                <button
                  className="button button--secondary"
                  disabled={removeJourney.isPending}
                  onClick={() => {
                    if (window.confirm(`确定删除 ${journey.journey_code}？此操作无法撤销。`)) {
                      removeJourney.mutate(journey.id);
                    }
                  }}
                  type="button"
                >
                  删除
                </button>
              </div>
            </article>
            );
          })}
        </div>
      ) : null}
      {journeys.data && journeys.data.total > 0 ? (
        <nav className="table-pagination" aria-label="行程分页">
          <span>
            第 {journeys.data.offset + 1}–
            {journeys.data.offset + journeys.data.items.length} 条，共 {journeys.data.total} 条
          </span>
          <div>
            <button
              className="button button--secondary"
              disabled={page === 0 || journeys.isFetching}
              onClick={() => setPage((current) => Math.max(0, current - 1))}
              type="button"
            >
              上一页
            </button>
            <button
              className="button button--secondary"
              disabled={!journeys.data.has_more || journeys.isFetching}
              onClick={() => setPage((current) => current + 1)}
              type="button"
            >
              下一页
            </button>
          </div>
        </nav>
      ) : null}
      {filter && journeys.data?.items.length && filteredItems.length === 0 ? (
        <p className="panel-message">没有符合筛选条件的行程。</p>
      ) : null}
      {reResolve.isError ? <p className="form-message form-message--error" role="alert">路径仍有歧义，不能自动重算；原行程未改变。</p> : null}
      {previewRail.isError ? (
        <p className="form-message form-message--error" role="alert">
          {mutationErrorMessage(previewRail.error, "铁路候选预览失败，原行程未改变。")}
        </p>
      ) : null}
      {removeJourney.isError ? <p className="form-message form-message--error" role="alert">删除失败，行程仍保留在本机，请重试。</p> : null}
      {editing ? (
        <ModalDialog
          className="journey-edit-dialog"
          labelledBy="journey-edit-title"
          onClose={() => setEditing(undefined)}
        >
          <form
            onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              const traveledAt = form.get("traveled_at");
              const note = form.get("note");
              updateJourney.mutate({
                id: editing.id,
                traveledAt: typeof traveledAt === "string" && traveledAt ? traveledAt : null,
                note: typeof note === "string" && note.trim() ? note.trim() : null,
                expectedUpdatedAt: editing.updated_at,
              });
            }}
          >
            <h2 id="journey-edit-title">编辑 {editing.journey_code}</h2>
            <label className="field"><span className="field__label">乘坐日期</span><input autoFocus defaultValue={editing.traveled_at ?? ""} name="traveled_at" type="date" /></label>
            <label className="field"><span className="field__label">备注</span><textarea defaultValue={editing.note ?? ""} maxLength={2000} name="note" rows={3} /></label>
            <div className="journey-edit-dialog__actions">
              <button className="button button--secondary" onClick={() => setEditing(undefined)} type="button">取消</button>
              <button className="button button--primary" disabled={updateJourney.isPending} type="submit">保存修改</button>
            </div>
          </form>
        </ModalDialog>
      ) : null}
      {railRecompute ? (
        <RailRecomputeDialog
          error={recomputeRail.error}
          isSaving={recomputeRail.isPending}
          journey={railRecompute.journey}
          onClose={() => setRailRecompute(undefined)}
          onConfirm={(input) =>
            recomputeRail.mutate({
              journeyId: railRecompute.journey.id,
              input,
            })
          }
          preview={railRecompute.preview}
        />
      ) : null}
    </section>
  );
}
