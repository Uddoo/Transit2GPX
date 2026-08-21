import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import {
  deleteJourney,
  fetchJourneys,
  patchJourney,
  reResolveJourney,
  type Journey,
} from "../../api/client";
import { ModalDialog } from "../../components/ModalDialog";

export function JourneysPage() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState<Journey>();
  const journeys = useQuery({
    queryKey: ["journeys"],
    queryFn: ({ signal }) => fetchJourneys(signal),
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
  const filteredItems = useMemo(() => {
    const key = filter.trim().toLocaleLowerCase();
    if (!key) return journeys.data?.items ?? [];
    return (journeys.data?.items ?? []).filter((journey) =>
      [
        journey.journey_code,
        journey.note ?? "",
        ...journey.legs.flatMap((leg) => [
          leg.city_name,
          leg.line_name,
          leg.start_station_name,
          leg.end_station_name,
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
        <span>{filteredItems.length} 条</span>
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
          {filteredItems.map((journey) => (
            <article className="journey-card" key={journey.id}>
              <div className="journey-card__main">
                <div className="journey-card__meta">
                  <strong>{journey.traveled_at ?? "日期未填写"}</strong>
                  <span>{journey.journey_code}</span>
                </div>
                <h2>
                  {journey.legs.map((leg) => (
                    <span key={leg.id}>
                      {leg.city_name} · {leg.line_name} · {leg.start_station_name} → {leg.end_station_name}
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
                          数据版本 {leg.dataset_version_id} · {leg.edge_ids.length} 个区间 ·
                          {" "}{leg.direction ?? "方向未标注"} · {leg.resolution_status}
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
                  disabled={reResolve.isPending}
                  onClick={() => reResolve.mutate(journey.id)}
                  type="button"
                >
                  重算
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
          ))}
        </div>
      ) : null}
      {filter && journeys.data?.items.length && filteredItems.length === 0 ? (
        <p className="panel-message">没有符合筛选条件的行程。</p>
      ) : null}
      {reResolve.isError ? <p className="form-message form-message--error" role="alert">路径仍有歧义，不能自动重算；原行程未改变。</p> : null}
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
    </section>
  );
}
