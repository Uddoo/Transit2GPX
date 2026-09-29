import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { inspectCityPack, installCityPack } from "../../api/client";
import { errorMessage } from "./setupHelpers";
import { SetupNotice } from "./SetupShared";

type Props = { refresh: () => Promise<void>; disabled?: boolean; onBusyChange?: (busy: boolean) => void; onInstalled?: () => void };

export function CityPackImport({ refresh, disabled = false, onBusyChange, onInstalled }: Props) {
  const [filename, setFilename] = useState("");
  const inspect = useMutation({ mutationFn: inspectCityPack });
  const install = useMutation({ mutationFn: installCityPack, onSuccess: async () => { await refresh(); onInstalled?.(); } });
  const busy = inspect.isPending || install.isPending;
  useEffect(() => { onBusyChange?.(busy); return () => onBusyChange?.(false); }, [busy, onBusyChange]);
  const preview = inspect.data;
  return <div className="setup-city-pack">
    <p>选择下载好的 .t2fcity 文件，无需解压。安装前会检查来源与文件完整性。</p>
    <label className="field"><span className="field__label">选择城市数据包</span><input type="file" accept=".t2fcity" disabled={busy || disabled} onChange={(event) => {
      const file = event.target.files?.[0];
      event.currentTarget.value = "";
      if (!file) return;
      setFilename(file.name);
      inspect.reset(); install.reset();
      inspect.mutate(file);
    }} /></label>
    {inspect.isPending ? <p role="status">正在检查城市包的完整性与线路拓扑…</p> : null}
    {filename && !preview ? <p className="setup-caption">已选择：{filename}</p> : null}
    {inspect.isError || install.isError ? <div className="city-error" role="alert"><p>{errorMessage(inspect.error ?? install.error, "城市包导入失败，请重新选择有效文件。")}</p><p>可重新下载后选择同一个文件；已有城市和行程不受影响。</p></div> : null}
    {preview && !inspect.isPending && !inspect.isError ? <SetupNotice title={`${preview.manifest.city_name} · ${preview.manifest.source.captured_at ?? "本地数据包"}`}>
      <p>{preview.stations} 个站点 · {preview.ready_variants} 条可用线路方向{preview.blocked_variants ? ` · ${preview.blocked_variants} 条方向暂不可用` : ""}</p>
      <p>数据时间：{preview.manifest.source.captured_at ?? "未提供"} · 许可：{preview.manifest.source.license}</p>
      <details className="city-source"><summary>来源、许可与版本</summary><p>{preview.manifest.source.attribution}</p><p>版本：{preview.manifest.source.version}</p></details>
      {install.isSuccess ? <p role="status">城市包已安装，可选择起终点并导出轨迹。</p> : <button type="button" className="button button--primary" disabled={busy || disabled} onClick={() => install.mutate(preview.package_id)}>{install.isPending ? "正在安装城市数据…" : "安装城市数据"}</button>}
    </SetupNotice> : null}
  </div>;
}
