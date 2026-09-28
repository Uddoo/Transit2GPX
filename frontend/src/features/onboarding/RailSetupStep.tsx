import { errorMessage, RAIL_GUIDE } from "./setupHelpers";
import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { checkRailSetup, startSetupRailService, startRailDataImport, type RailSetupConfig, type SetupState, type SetupProgressPatch } from "../../api/client";
import { SetupCheckList, SetupNotice } from "./SetupShared";

type Props = { state: SetupState; refresh: () => Promise<void>; save: (patch: SetupProgressPatch) => Promise<unknown>; next: (skip: boolean) => void; busy: boolean; onBusyChange: (busy: boolean) => void };
export function RailSetupStep({ state, refresh, save, next, busy, onBusyChange }: Props) {
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; onBusyChange(false); }; }, [onBusyChange]);
  const [config, setConfig] = useState<RailSetupConfig>(state.rail_config);
  const ready = state.rail.status === "ready";
  const checks = useMutation({ mutationFn: checkRailSetup, onSuccess: refresh });
  const start = useMutation({ mutationFn: async () => {
    const result = await checks.mutateAsync(config);
    if (!result.can_continue || !mounted.current) return null;
    await save({ step: "rail", rail_skipped: false });
    return mounted.current ? startSetupRailService(config) : null;
  }, onSuccess: refresh });
  const index = useMutation({ mutationFn: () => startRailDataImport({
    pbf_path: state.rail_config.pbf_path ?? config.pbf_path ?? "",
    graph_version: state.rail_config.graph_version ?? "active",
  }), onSuccess: refresh });
  useEffect(() => onBusyChange(start.isPending || checks.isPending || index.isPending), [start.isPending, checks.isPending, index.isPending, onBusyChange]);
  const starting = start.isPending || checks.isPending || state.service.status === "starting";
  const checkingOnly = checks.isPending && !start.isPending && state.service.status !== "starting";
  const indexing = index.isPending || state.rail.status === "importing";
  const serviceReady = state.service.status === "ready";
  const failedCheck = checks.data?.checks.find((check) => check.status === "failed");
  function field(key: keyof RailSetupConfig, label: string, placeholder: string, required = false) {
    return <label className="field"><span className="field__label">{label}</span><input
      value={config[key] ?? ""} onChange={(event) => setConfig((current) => ({ ...current, [key]: event.target.value || (required ? "" : null) }))}
      disabled={starting || serviceReady || ready || state.locked_fields.includes(key)} placeholder={placeholder} required={required} maxLength={key === "graph_version" ? 160 : 480} autoComplete="off" />
    </label>;
  }
  return <>
    <h2>准备铁路服务</h2><p className="setup-lead">已有铁路图？填写本机路径，启动后即可导入车站索引。 {!ready ? <a className="setup-help-link" href={RAIL_GUIDE} target="_blank" rel="noreferrer">准备说明 ↗</a> : null}</p>
    {ready ? <SetupNotice title="铁路数据已就绪"><p>{state.rail.station_count.toLocaleString()} 个车站 · 图版本 {state.rail.graph_version}</p><p>铁路服务与车站索引均已通过检查。</p></SetupNotice> : null}
    <form className="setup-form" onSubmit={(event) => { event.preventDefault(); start.mutate(); }}>
      {field("graph_root", "铁路图目录", "填写 graphs 目录的完整路径", true)}
      <div className="setup-form__pair">{field("graph_version", "图版本", "active", true)}{field("pbf_path", "铁路 PBF 文件", "可留空，由图元数据定位")}</div>
      <details className="setup-details"><summary>高级设置：Java 与服务文件</summary>
        {field("java_home", "Java 安装目录", "可留空，自动查找 Java")}
        {field("jar_path", "铁路服务 JAR 文件", "填写 openrailrouting.jar 的完整路径")}
        {state.locked_fields.length ? <p className="setup-caption">部分选项由启动参数或环境变量管理；修改这些选项需要调整启动配置并重新打开应用。</p> : null}
      </details>
      {!state.rail_start_allowed ? <SetupNotice warning title="启动配置禁用了托管铁路服务"><p>请按铁路准备说明启用铁路与托管启动，重新打开应用后继续。也可以先使用地铁。</p></SetupNotice> : null}
      {failedCheck && !starting ? <SetupNotice warning title={failedCheck.detail} action={<button className="button button--secondary" onClick={() => checks.mutate(config)} type="button">重新检查</button>}><p>{failedCheck.remedy}</p></SetupNotice> : null}
      {state.service.status === "failed" ? <SetupNotice warning title="铁路服务尚未启动"><p>{state.service.message}</p><p>{state.service.error_code?.includes("checksum") || state.service.error_code?.includes("identity") ? "请确认铁路图、PBF 和服务版本属于同一套数据，保留原文件后重新核对。" : "核对文件路径、Java 版本，并检查日志中的端口占用或内存不足信息。地铁功能仍可使用。"}</p></SetupNotice> : null}
      {checks.isError || start.isError ? <SetupNotice warning title="未能完成启动检查"><p>{errorMessage(start.error ?? checks.error, "请确认本地服务连接正常后重试。")}</p></SetupNotice> : null}
      {starting ? <div className="setup-progress" role="status"><strong>{checkingOnly ? "正在检查铁路环境…" : "正在校验文件并启动铁路服务…"}</strong><p>大文件校验可能需要一些时间，可以稍后回来查看。</p><progress aria-label={checkingOnly ? "铁路环境检查进度" : "铁路服务启动进度"} /></div> : null}
      {!ready && !serviceReady ? <div className="setup-actions"><button className="button button--secondary" onClick={() => next(true)} disabled={busy} type="button">跳过，先使用地铁</button><button className="button button--primary" disabled={starting || !state.rail_start_allowed} type="submit">{checkingOnly ? "正在检查…" : starting ? "正在启动…" : "启动铁路服务"}</button></div> : null}
    </form>
    {serviceReady && !ready ? <div className="setup-index">
      <SetupNotice title="路径服务已启动，还需准备车站索引"><p>从同一份 PBF 导入车站后，才能搜索车站并创建铁路行程。</p></SetupNotice>
      {indexing ? <p role="status">正在导入车站索引… 当前 {state.rail.station_count} 个车站。刷新后可以继续查看。</p> : null}
      {index.isError || state.rail.error_message ? <p className="setup-caption" role={index.isError ? "alert" : undefined}>{index.isError ? errorMessage(index.error, "车站索引导入失败，请核对 PBF 文件后重试。") : state.rail.error_message}</p> : null}
      <button className="button button--primary" disabled={indexing || !(state.rail_config.pbf_path ?? config.pbf_path)} onClick={() => index.mutate()} type="button">{indexing ? "正在导入车站…" : "导入车站索引"}</button>
      <button className="button button--secondary" disabled={busy} onClick={() => next(true)} type="button">稍后完成铁路设置</button>
    </div> : null}
    {ready ? <div className="setup-actions"><button className="button button--primary" onClick={() => next(false)} disabled={busy} type="button">下一步：开始使用</button></div> : null}
    <details className="setup-diagnostics"><summary>故障诊断与日志</summary>{checks.data ? <SetupCheckList checks={checks.data.checks} /> : null}<dl><div><dt>服务状态</dt><dd>{state.service.status}</dd></div><div><dt>错误代码</dt><dd>{state.service.error_code ?? state.rail.error_code ?? "无"}</dd></div><div><dt>铁路日志</dt><dd>{state.log_path}</dd></div></dl><a href={RAIL_GUIDE} target="_blank" rel="noreferrer">查看排障说明 ↗</a></details>
  </>;
}
