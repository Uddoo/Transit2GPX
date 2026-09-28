import { NavLink, Outlet, useLocation } from "react-router-dom";
import { Suspense } from "react";

import { useDataStatus } from "../features/data-settings/useDataStatus";
import { useRailDataStatus } from "../features/journey-editor/useJourneyNetwork";
import { Icon, type IconName } from "../components/Icon";

type NavigationItem = {
  label: string;
  to: string;
  icon: IconName;
};

const NAV_ITEMS: NavigationItem[] = [
  { label: "行程", to: "/journeys", icon: "list" },
  { label: "添加行程", to: "/journeys/new", icon: "plus" },
  { label: "CSV 导入", to: "/imports/csv", icon: "download" },
  { label: "导出", to: "/exports", icon: "export" },
  { label: "数据与设置", to: "/settings/data", icon: "settings" },
];

function StatusLabel() {
  const metro = useDataStatus();
  const rail = useRailDataStatus();
  const railStatusLabel =
    rail.data?.status === "ready"
      ? (rail.data.graph_version ?? "铁路数据")
      : null;

  if (metro.isError && rail.isError) {
    return <span>本地服务未连接</span>;
  }
  if ((!metro.data || metro.data.status === "not_configured") && railStatusLabel) {
    return <span>{railStatusLabel} · 铁路就绪</span>;
  }
  if (!metro.data || metro.data.status === "not_configured") {
    return <span>尚未导入地铁数据</span>;
  }
  if (metro.data.status === "importing") {
    return <span>{metro.data.ready_available ? "正在导入 · 现有数据可用" : "正在导入地铁数据"}</span>;
  }
  if (metro.data.status === "failed" || metro.data.status === "cancelled") {
    if (!metro.data.ready_available && railStatusLabel) {
      return <span>{railStatusLabel} · 铁路就绪</span>;
    }
    return <span>{metro.data.ready_available ? "新导入未完成 · 现有数据可用" : "没有可用地铁数据"}</span>;
  }
  return (
    <span>
      {metro.data.dataset ?? "地铁数据"} · 地铁就绪
      {railStatusLabel ? " · 铁路就绪" : ""}
    </span>
  );
}

function Brand() {
  return (
    <NavLink className="brand" to="/journeys/new" aria-label="Transit2Fog 首页">
      <span className="brand__name">Transit2Fog</span>
      <span className="brand__tagline">
        记录真实地铁与铁路行程，导出 Fog of World 可用的 GPX
      </span>
    </NavLink>
  );
}

function Navigation({ mobile = false }: { mobile?: boolean }) {
  return (
    <nav className={mobile ? "mobile-nav" : "top-nav"} aria-label="主要导航">
      {NAV_ITEMS.map((item) => (
        <NavLink
          end={item.to === "/journeys"}
          key={item.to}
          to={item.to}
          className={({ isActive }) =>
            `${mobile ? "mobile-nav__item" : "top-nav__item"}${
              isActive ? " is-active" : ""
            }`
          }
        >
          <Icon name={item.icon} size={mobile ? 21 : 19} />
          <span>{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}

function TodayLabel() {
  const parts = new Intl.DateTimeFormat("zh-CN", {
    day: "2-digit",
    month: "2-digit",
    weekday: "short",
    year: "numeric",
  })
    .formatToParts(new Date());
  const value = (type: "day" | "month" | "weekday" | "year") =>
    parts.find((part) => part.type === type)?.value ?? "";
  const today = `${value("year")}-${value("month")}-${value("day")} ${value("weekday").replace("周", "星期")}`;

  return <span>{today}</span>;
}

export function AppShell() {
  const location = useLocation();
  const mobileTitle =
    NAV_ITEMS.find((item) => location.pathname.startsWith(item.to))?.label ??
    "Transit2Fog";

  return (
    <div className="app-shell">
      <header className="topbar">
        <Brand />
        <Navigation />
      </header>

      <header className="mobile-header">
        <NavLink className="icon-button" to="/journeys/new" aria-label="Transit2Fog 首页">
          <Icon name="train" size={22} />
        </NavLink>
        <strong>{mobileTitle}</strong>
        <span className="mobile-header__status" aria-label="数据状态">
          <Icon name="database" size={18} />
        </span>
      </header>

      <div className="workspace">
        <header className="status-bar" aria-label="应用状态">
          <div className="status-bar__date">
            <Icon name="database" size={17} />
            <TodayLabel />
          </div>
          <div className="status-bar__status">
            <Icon name="database" size={18} />
            <StatusLabel />
          </div>
        </header>
        <main className="page" id="main-content">
          <Suspense fallback={<p className="panel-message" role="status">正在加载页面…</p>}>
            <Outlet />
          </Suspense>
        </main>
      </div>

      <Navigation mobile />
    </div>
  );
}
