import { useMutation } from "@tanstack/react-query";
import { prepareRailComponents, type ComponentState } from "../../api/client";
import { SetupNotice } from "./SetupShared";
import { errorMessage } from "./setupHelpers";

type Props = { state: ComponentState; disabled: boolean; refresh: () => Promise<void> };
const mib = (bytes: number) => (bytes / 1024 ** 2).toFixed(1);

export function RailComponents({ state, disabled, refresh }: Props) {
  const install = useMutation({ mutationFn: prepareRailComponents, onSuccess: refresh });
  if (state.status === "unavailable") return null;
  const running = state.status === "downloading" || state.status === "installing";
  return <div className="setup-components">
    <SetupNotice title={state.status === "ready" ? "铁路组件已就绪" : "一键准备铁路组件"}>
      <p>{state.status === "ready" ? "铁路引擎和专用 Java 已保存在本机，无需另装 Java。继续准备下方的铁路图和 PBF。" : `首次使用需下载约 ${mib(state.total_bytes)} MiB，自动安装铁路引擎和专用 Java。不会修改系统 Java；地铁功能可继续使用。`}</p>
      <p className="setup-caption">组件不包含铁路图和 PBF 数据，下载完成不代表铁路数据已就绪。</p>
      {running ? <div className="setup-progress" role="status">
        <strong>{state.message}</strong>
        <progress aria-label="铁路组件下载进度" value={state.status === "downloading" ? state.downloaded_bytes : undefined} max={state.total_bytes || 1} />
        <p>{mib(state.downloaded_bytes)} / {mib(state.total_bytes)} MiB · 可以稍后回来查看</p>
      </div> : null}
      {state.status === "failed" || install.isError ? <p role="alert">{install.isError ? errorMessage(install.error, "暂时无法准备组件，请重试。") : state.message}</p> : null}
      {state.status !== "ready" ? <button className="button button--primary" type="button" disabled={disabled || running || install.isPending} onClick={() => install.mutate()}>
        {running || install.isPending ? "正在准备组件…" : state.status === "failed" ? "重试组件下载" : "下载并准备铁路组件"}
      </button> : null}
    </SetupNotice>
  </div>;
}
