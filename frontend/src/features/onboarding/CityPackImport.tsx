import { useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { inspectCityPack, installCityPack } from "../../api/client";
import { errorMessage } from "./setupHelpers";
import { SetupNotice } from "./SetupShared";

type Props = { refresh: () => Promise<void>; disabled?: boolean; onBusyChange?: (busy: boolean) => void };

export function CityPackImport({ refresh, disabled = false, onBusyChange }: Props) {
  const inspect = useMutation({ mutationFn: inspectCityPack });
  const install = useMutation({ mutationFn: installCityPack, onSuccess: refresh });
  const busy = inspect.isPending || install.isPending;
  useEffect(() => { onBusyChange?.(busy); return () => onBusyChange?.(false); }, [busy, onBusyChange]);
  const preview = inspect.data;
  return <div className="setup-city-pack">
    <h3>标准城市数据包</h3>
    <p>选择 .t2fcity 文件即可安装，无需解压、填写目录或安装地理数据处理库。更新城市时会保留已有行程。</p>
    <label className="field"><span className="field__label">选择城市数据包</span><input type="file" accept=".t2fcity" disabled={busy || disabled} onChange={(event) => {
      const file = event.target.files?.[0];
      inspect.reset(); install.reset();
      if (file) inspect.mutate(file);
    }} /></label>
    {inspect.isPending ? <p role="status">正在检查城市包的完整性与线路拓扑…</p> : null}
    {inspect.isError || install.isError ? <p role="alert">{errorMessage(inspect.error ?? install.error, "城市包导入失败，请重新选择有效文件。")}</p> : null}
    {preview && !inspect.isPending && !inspect.isError ? <SetupNotice title={`${preview.manifest.city_name} · ${preview.manifest.source.version}`}>
      <p>{preview.lines} 条线路 · {preview.stations} 个站点 · {preview.ready_variants} 个可用方向{preview.blocked_variants ? ` · ${preview.blocked_variants} 个阻断方向` : ""}</p>
      <p>数据时间：{preview.manifest.source.captured_at ?? "未提供"} · 许可：{preview.manifest.source.license}</p>
      <p className="setup-caption">{preview.manifest.source.attribution}</p>
      {install.isSuccess ? <p role="status">城市包已安装，可选择起终点并导出轨迹。</p> : <button type="button" className="button button--primary" disabled={busy || disabled} onClick={() => install.mutate(preview.package_id)}>{install.isPending ? "正在安装城市数据…" : "安装城市数据"}</button>}
    </SetupNotice> : null}
  </div>;
}
