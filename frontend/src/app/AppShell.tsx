import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useDataStatus } from "../features/data-settings/useDataStatus";
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
  const query = useDataStatus();

  if (query.isError) {
    return <span>本地服务未连接</span>;
  }
  if (!query.data || query.data.status === "not_configured") {
    return <span>尚未导入地铁数据</span>;
  }
  if (query.data.status === "importing") {
    return <span>{query.data.ready_available ? "正在导入 · 现有数据可用" : "正在导入地铁数据"}</span>;
  }
  if (query.data.status === "failed" || query.data.status === "cancelled") {
    return <span>{query.data.ready_available ? "新导入未完成 · 现有数据可用" : "没有可用地铁数据"}</span>;
  }
  return <span>{query.data.dataset ?? "数据集"} · 数据就绪</span>;
}

function Brand() {
  return (
    <NavLink className="brand" to="/journeys/new" aria-label="Metro2Fog 首页">
      <span className="brand__mark" aria-hidden="true">
        <Icon name="train" size={22} />
      </span>
      <span>Metro2Fog</span>
    </NavLink>
  );
}

function Navigation({ mobile = false }: { mobile?: boolean }) {
  return (
    <nav className={mobile ? "mobile-nav" : "side-nav"} aria-label="主要导航">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) =>
            `${mobile ? "mobile-nav__item" : "side-nav__item"}${
              isActive ? " is-active" : ""
            }`
          }
        >
          <Icon name={item.icon} size={mobile ? 21 : 20} />
          <span>{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}

export function AppShell() {
  const location = useLocation();
  const mobileTitle =
    NAV_ITEMS.find((item) => location.pathname.startsWith(item.to))?.label ??
    "Metro2Fog";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Brand />
        <Navigation />
      </aside>

      <header className="mobile-header">
        <NavLink className="icon-button" to="/journeys/new" aria-label="Metro2Fog 首页">
          <Icon name="train" size={22} />
        </NavLink>
        <strong>{mobileTitle}</strong>
        <span className="mobile-header__status" aria-label="数据状态">
          <Icon name="database" size={18} />
        </span>
      </header>

      <div className="workspace">
        <header className="utility-bar" aria-label="应用状态">
          <div className="utility-bar__status">
            <Icon name="database" size={18} />
            <StatusLabel />
          </div>
        </header>
        <main className="page" id="main-content">
          <Outlet />
        </main>
      </div>

      <Navigation mobile />
    </div>
  );
}
