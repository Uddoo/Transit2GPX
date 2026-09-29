import { errorMessage, SETUP_GUIDE } from "./setupHelpers";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { fetchSetup, fetchSetupChecks, updateSetupProgress, type SetupProgressPatch, type SetupStep } from "../../api/client";
import { Icon } from "../../components/Icon";
import { MetroSetupStep } from "./MetroSetupStep";
import { RailSetupStep } from "./RailSetupStep";
import { SetupCheckList, SetupNotice } from "./SetupShared";
import "./onboarding.css";

const STEPS: { id: SetupStep; title: string }[] = [{ id: "check", title: "环境检查" }, { id: "metro", title: "地铁数据" }, { id: "rail", title: "铁路服务" }, { id: "finish", title: "开始使用" }];

export function OnboardingPage() {
  const client = useQueryClient();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const title = useRef<HTMLDivElement>(null);
  const preferredCity = useRef<number | null>(null);
  const mounted = useRef(true);
  const [actionBusy, setActionBusy] = useState(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const setup = useQuery({ queryKey: ["setup"], queryFn: ({ signal }) => fetchSetup(signal), retry: false,
    refetchInterval: (query) => query.state.data?.service.status === "starting" || query.state.data?.metro.status === "importing" || query.state.data?.rail.status === "importing" ? 1200 : params.get("step") === "rail" || (!params.get("step") && query.state.data?.progress.step === "rail") ? 2500 : false,
  });
  const checks = useQuery({ queryKey: ["setup-checks"], queryFn: ({ signal }) => fetchSetupChecks(signal), retry: false });
  const requested = params.get("step");
  const step = STEPS.find((item) => item.id === requested)?.id ?? setup.data?.progress.step ?? "check";
  const refresh = async () => {
    await Promise.all([client.invalidateQueries({ queryKey: ["setup"] }), client.invalidateQueries({ queryKey: ["data-status"] }), client.invalidateQueries({ queryKey: ["rail-data-status"] }), client.invalidateQueries({ queryKey: ["cities"] })]);
  };
  const progress = useMutation({ mutationFn: updateSetupProgress, onSuccess: async (_, patch) => {
    if (mounted.current && patch.step) setParams({ step: patch.step });
    await refresh();
    if (mounted.current && (patch.dismissed || patch.complete)) void navigate(patch.complete && preferredCity.current ? `/journeys/new?city=${preferredCity.current}` : "/journeys/new");
  }});
  const save = (patch: SetupProgressPatch) => progress.mutateAsync(patch);
  useEffect(() => { title.current?.focus(); }, [step]);
  const state = setup.data;
  const metroReady = Boolean(state?.metro.ready_available);
  const railReady = state?.rail.status === "ready";
  const complete = [checks.data?.can_continue, metroReady, railReady || state?.progress.rail_skipped, state?.progress.completed];

  return <section className="setup-shell" aria-labelledby="setup-title">
    <header className="setup-header"><div><h1 id="setup-title">开始使用 Transit2Fog</h1><p>准备一个城市的数据，即可开始记录真实乘坐。</p></div><button className="setup-text-action" disabled={progress.isPending || actionBusy} onClick={() => progress.mutate({ dismissed: true })} type="button">稍后设置</button></header>
    <div className="setup-layout"><aside className="setup-rail"><nav aria-label="首次使用步骤"><ol>{STEPS.map((item, index) => <li key={item.id} className={step === item.id ? "is-active" : complete[index] ? "is-complete" : ""}>
      <button aria-current={step === item.id ? "step" : undefined} disabled={progress.isPending || actionBusy || !state} onClick={() => progress.mutate({ step: item.id })} type="button"><span className="setup-step-number">{step !== item.id && complete[index] ? <Icon name="check" size={21} /> : `0${index + 1}`}</span><span>{item.title}{item.id === "rail" ? <small>可选</small> : null}</span></button>
    </li>)}</ol></nav><p>进度会自动保存</p></aside>
      <div className="setup-body"><div className="setup-panel" ref={title} tabIndex={-1}>
        {setup.isPending ? <p className="panel-message" role="status">正在读取设置进度…</p> : null}
        {setup.isError ? <SetupNotice warning title="无法连接本地服务"><p>请确认 Transit2Fog 正在运行，然后重新连接。</p><button className="button button--secondary" onClick={() => void setup.refetch()} type="button">重新连接</button> <a href={SETUP_GUIDE} target="_blank" rel="noreferrer">查看启动说明 ↗</a></SetupNotice> : null}
        {state && step === "check" ? <>
          <h2>先检查运行环境</h2><p className="setup-lead">确认本地服务和数据存储可用。铁路所需的 Java 会在第三步检查。</p>
          {checks.isPending ? <p role="status">正在检查本地环境…</p> : null}
          {checks.isError ? <SetupNotice warning title="环境检查暂时不可用"><p>确认本地服务运行正常后重新检查。</p></SetupNotice> : null}
          {checks.data ? <SetupCheckList checks={checks.data.checks} /> : null}
          <div className="setup-actions"><button className="button button--secondary" disabled={checks.isFetching} onClick={() => void checks.refetch()} type="button">{checks.isFetching ? "正在检查…" : "重新检查"}</button><button className="button button--primary" disabled={!checks.data?.can_continue || checks.isError || progress.isPending} onClick={() => progress.mutate({ step: "metro" })} type="button">下一步：导入地铁数据</button></div>
        </> : null}
        {state && step === "metro" ? <MetroSetupStep state={state} refresh={refresh} save={save} busy={progress.isPending || actionBusy} onBusyChange={setActionBusy} begin={(cityId) => { preferredCity.current = cityId ?? null; progress.mutate({ rail_skipped: true, complete: true }); }} next={() => progress.mutate({ step: "rail" })} /> : null}
        {state && step === "rail" ? <RailSetupStep state={state} refresh={refresh} save={save} busy={progress.isPending || actionBusy} onBusyChange={setActionBusy} next={(skip) => progress.mutate({ step: "finish", rail_skipped: skip })} /> : null}
        {state && step === "finish" ? <>
          <h2>{metroReady || railReady ? "可以开始记录了" : "还差一份线路数据"}</h2><p className="setup-lead">设置会保存在本机，你可以随时回到向导继续准备。</p>
          <ul className="setup-summary"><li><Icon name="train" /><div><strong>地铁</strong><p>{metroReady ? "已安装城市数据，可开始选站" : "尚未准备，可在第二步导入数据"}</p></div><span>{metroReady ? "可使用" : "待准备"}</span></li><li><Icon name="train" /><div><strong>铁路 / 高铁</strong><p>{railReady ? `${state.rail.station_count.toLocaleString()} 个车站，服务已连接` : state.progress.rail_skipped ? "已跳过，可稍后准备" : "服务和车站索引尚未全部就绪"}</p></div><span>{railReady ? "可使用" : state.progress.rail_skipped ? "已跳过" : "待准备"}</span></li></ul>
          <p className="setup-caption">创建一段真实乘坐记录，确认候选路径后即可导出 GPX。</p>
          <div className="setup-actions"><button className="button button--secondary" disabled={progress.isPending || actionBusy} onClick={() => progress.mutate({ step: !metroReady ? "metro" : "rail" })} type="button">继续准备数据</button><button className="button button--primary" disabled={progress.isPending || !(metroReady || railReady) || !checks.data?.can_continue} onClick={() => progress.mutate({ complete: true })} type="button">开始记录行程</button></div>
        </> : null}
        {progress.isError ? <p className="form-message form-message--error" role="alert">{errorMessage(progress.error, "进度保存失败，请确认本地服务可用后重试。")}</p> : null}
      </div><div className="setup-helper"><Icon name="info" size={19} /><span>{step === "rail" ? "已有就绪数据会保留。铁路服务只在本机运行。" : "只用地铁？可以跳过铁路准备，随时回来继续。"}</span></div><Link className="setup-return" to="/journeys/new">返回应用</Link></div>
    </div>
  </section>;
}
