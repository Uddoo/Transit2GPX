import { type SetupChecks } from "../../api/client";
import { Icon, type IconName } from "../../components/Icon";

export function SetupNotice({ title, children, warning = false, action }: { title: string; children: React.ReactNode; warning?: boolean; action?: React.ReactNode }) {
  return <div className={`setup-notice${warning ? " setup-notice--warning" : ""}`} role={warning ? "alert" : "status"}>
    <Icon name="info" size={21} />
    <div className="setup-notice__copy"><strong>{title}</strong><div>{children}</div></div>
    {action ? <div className="setup-notice__action">{action}</div> : null}
  </div>;
}

const icons: Record<string, IconName> = { service: "server", database: "database", storage: "folder", disk: "drive", java: "settings", jar: "settings", config: "settings", graph: "train", pbf: "database" };
export function SetupCheckList({ checks }: { checks: SetupChecks["checks"] }) {
  return <ul className="setup-checks">{checks.map((check) => <li key={check.id}>
    <Icon name={icons[check.id] ?? "settings"} size={27} />
    <div className="setup-checks__copy"><strong>{check.title}</strong><p>{check.detail}</p>{check.remedy ? <small>{check.remedy}</small> : null}</div>
    <span className={`setup-check-state setup-check-state--${check.status}`}>
      {check.status === "passed" ? <Icon name="check" size={18} /> : <Icon name="info" size={18} />}
      {check.status === "passed" ? "已就绪" : check.status === "warning" ? "请留意" : "待处理"}
    </span>
  </li>)}</ul>;
}
