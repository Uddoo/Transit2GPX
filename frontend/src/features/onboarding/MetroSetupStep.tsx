import { errorMessage, SETUP_GUIDE } from "./setupHelpers";
import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { cancelDatasetImport, startDatasetImport, type SetupProgressPatch, type SetupState } from "../../api/client";
import { SetupNotice } from "./SetupShared";
import { CityDataManager } from "./CityDataManager";

type Props = { state: SetupState; refresh: () => Promise<void>; save: (patch: SetupProgressPatch) => Promise<unknown>; begin: (cityId?: number) => void; next: () => void; busy: boolean; onBusyChange: (busy: boolean) => void };
export function MetroSetupStep({ state, refresh, save, begin, next, busy, onBusyChange }: Props) {
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; onBusyChange(false); }; }, [onBusyChange]);
  const [directory, setDirectory] = useState(state.metro_directory);
  const metro = state.metro;
  const readyPanel = useRef<HTMLDivElement>(null);
  const wasReady = useRef(metro.ready_available);
  useEffect(() => { if (!wasReady.current && metro.ready_available) readyPanel.current?.focus(); wasReady.current = metro.ready_available; }, [metro.ready_available]);
  const importing = metro.status === "importing";
  const start = useMutation({ mutationFn: async () => {
    const path = directory.trim().replace(/^(["'])(.*)\1$/, "$2");
    await save({ step: "metro", metro_directory: path });
    return mounted.current ? startDatasetImport(path) : null;
  }, onSuccess: refresh });
  const cancel = useMutation({ mutationFn: () => cancelDatasetImport(metro.import_id as number), onSuccess: refresh });
  useEffect(() => onBusyChange(start.isPending || cancel.isPending), [start.isPending, cancel.isPending, onBusyChange]);
  const form = <form className="setup-form" onSubmit={(event) => { event.preventDefault(); start.mutate(); }}>
    <label className="field"><span className="field__label">地铁数据目录（本机绝对路径）</span><input value={directory} onChange={(event) => setDirectory(event.target.value)} disabled={importing || start.isPending || busy} placeholder="填写解压后数据目录的完整路径" required maxLength={480} autoComplete="off" /></label>
    <p className="setup-caption">保留同名的 .shp、.shx、.dbf、.prj 文件；目录下可以有子文件夹。</p>
    <button className="button button--primary" disabled={importing || start.isPending || busy || !directory.trim()} type="submit">{start.isPending ? "正在检查目录…" : "导入地铁数据"}</button>
  </form>;
  return <>
    <h2>导入地铁线路数据</h2><p className="setup-lead">推荐使用已经整理好的标准城市数据包，确认来源后即可安装。</p>
    {metro.ready_available ? <div className="metro-ready-action" ref={readyPanel} tabIndex={-1}><strong>地铁数据已就绪</strong><p>可以开始记录，铁路功能可稍后准备。</p><button className="button button--primary" onClick={() => begin()} disabled={busy} type="button">开始记录地铁行程</button></div> : null}
    <CityDataManager refresh={refresh} disabled={importing || start.isPending || busy} onBusyChange={onBusyChange} onStartCity={begin} />
    {state.raw_import_available !== false ? <details className="setup-details" open={importing || start.isError || metro.status === "cancelled" || undefined}><summary>高级：导入原始数据目录</summary>{form}<a href={SETUP_GUIDE} target="_blank" rel="noreferrer">原始数据准备说明 ↗</a></details> : null}
    {importing ? <div className="setup-progress" role="status"><strong>正在校验并构建线路拓扑</strong><p>已处理 {metro.processed_cities} / {metro.total_cities || "待扫描"} 个城市 · {metro.ready_lines} 条线路记录可用</p><progress aria-label="地铁数据导入进度" max={Math.max(metro.total_cities, 1)} value={metro.processed_cities} /><p>可以离开或刷新页面，进度会保留。</p><button className="button button--secondary" disabled={cancel.isPending} onClick={() => cancel.mutate()} type="button">取消导入</button></div> : null}
    {start.isError || metro.status === "failed" || metro.status === "cancelled" ? <SetupNotice warning title={metro.status === "cancelled" && !start.isError ? "导入已取消" : "地铁数据尚未准备好"}><p>{start.isError ? errorMessage(start.error, "目录检查失败，请确认本地服务可用后重试。") : metro.error_message}</p><p>确认目录和配套文件完整后，可以使用上方按钮重新导入。</p></SetupNotice> : null}
    {cancel.isError ? <p role="alert">取消失败，请重新读取任务状态后重试。</p> : null}
    {metro.blocked_lines > 0 ? <SetupNotice warning title="部分线路未通过质量检查"><p>{metro.blocked_lines} 条线路暂不可用，可用线路仍可正常使用。详情可在“数据与设置”中查看。</p></SetupNotice> : null}
    <div className="setup-actions"><button className="button button--secondary" onClick={next} disabled={busy} type="button">{metro.ready_available ? "继续设置铁路（可选）" : "跳过，先设置铁路"}</button></div>
  </>;
}
