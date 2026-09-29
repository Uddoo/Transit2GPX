import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Route, Routes, useLocation } from "react-router-dom";
import { renderApp } from "../../test/renderApp";
import { type SetupState } from "../../api/client";
import { OnboardingPage } from "./OnboardingPage";
import { SetupEntry } from "./SetupEntry";
import { initialSetupState, readyChecks, catalogFixture, idleCityDownload } from "../../test/setupFixtures";

function response(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }); }
function Location() { return <output data-testid="location">{useLocation().pathname}{useLocation().search}</output>; }

let state: SetupState;
let uploads: number;
let railChecks: number;
let offline: boolean;
let environmentFailed: boolean;
let saveFailed: boolean;
let railFailed: boolean;

beforeEach(() => {
  state = initialSetupState(); uploads = 0; railChecks = 0; offline = false; environmentFailed = false; saveFailed = false; railFailed = false;
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, "http://localhost");
    if (url.pathname === "/api/v1/data/city-packs/catalog") return Promise.resolve(response(catalogFixture));
    if (url.pathname === "/api/v1/data/city-packs/download") return Promise.resolve(response(idleCityDownload));
    if (url.pathname === "/api/v1/cities") return Promise.resolve(response([]));
    if (url.pathname === "/api/v1/setup") return Promise.resolve(offline ? response({ error: { message: "offline" } }, 503) : response(state));
    if (url.pathname === "/api/v1/setup/checks") return Promise.resolve(response(environmentFailed ? { can_continue: false, checks: [{ id: "database", title: "本地数据库", status: "failed", detail: "数据库需要升级", remedy: "重新启动安装包" }] } : readyChecks));
    if (url.pathname === "/api/v1/setup/progress") {
      if (saveFailed) return Promise.resolve(response({ error: { message: "进度保存暂时失败" } }, 503));
      const patch = JSON.parse(typeof init?.body === "string" ? init.body : "{}") as { step?: "check" | "metro" | "rail" | "finish"; dismissed?: boolean; rail_skipped?: boolean; complete?: boolean; metro_directory?: string };
      state.progress = { ...state.progress, ...patch, completed: patch.complete ?? state.progress.completed };
      state.metro_directory = patch.metro_directory ?? state.metro_directory;
      return Promise.resolve(response(state.progress));
    }
    if (url.pathname === "/api/v1/data/imports") {
      uploads += 1;
      if (uploads === 1) return Promise.resolve(response({ error: { message: "目录不存在，请核对路径" } }, 422));
      state.metro = { ...state.metro, status: uploads === 2 ? "importing" : "ready", ready_available: uploads > 2, import_id: 7, cities: uploads > 2 ? 1 : 0, total_cities: 2, processed_cities: 1, ready_lines: 1, error_message: null };
      return Promise.resolve(response({ import_id: 7, status: "staging" }, 202));
    }
    if (url.pathname === "/api/v1/data/imports/7/cancel") { state.metro.status = "cancelled"; state.metro.error_message = "已取消"; return Promise.resolve(response({ import_id: 7, status: "cancelled" })); }
    if (url.pathname === "/api/v1/setup/rail/check") {
      railChecks += 1;
      return Promise.resolve(response(railChecks === 1 ? { can_continue: false, checks: [{ id: "java", title: "Java 运行环境", status: "failed", detail: "没有找到 Java 17 或更高版本", remedy: "安装 Java 后重新检查" }] } : readyChecks));
    }
    if (url.pathname === "/api/v1/setup/rail/start") {
      if (railFailed) return Promise.resolve(response({ error: { code: "rail_sidecar_identity_mismatch", message: "服务与所选图版本不一致" } }, 409));
      state.service.status = "ready"; state.rail.status = "not_configured"; state.rail.enabled = true;
      return Promise.resolve(response({ status: "starting", error_code: null, message: "starting" }, 202));
    }
    if (url.pathname === "/api/v1/rail/data/imports") {
      state.rail = { ...state.rail, status: "ready", station_count: 48, graph_version: "active", sidecar_available: true };
      return Promise.resolve(response({ import_id: 9, status: "staging" }, 202));
    }
    throw new Error(`Unexpected request ${url.pathname}`);
  }));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function show(path = "/setup") { renderApp(<><OnboardingPage /><Location /></>, path); }

describe("first-use setup", () => {
  it("handles a bad directory, cancellation, retry, metro-only completion and persisted progress", async () => {
    const user = userEvent.setup(); show();
    await user.click(await screen.findByRole("button", { name: "下一步：导入地铁数据" }));
    await screen.findByRole("heading", { name: "导入地铁线路数据" });
    await user.click(screen.getByText("高级：导入原始数据目录"));
    await user.type(screen.getByLabelText("地铁数据目录（本机绝对路径）"), "/tmp/data");
    await user.click(screen.getByRole("button", { name: "导入地铁数据" }));
    expect(await screen.findByText("目录不存在，请核对路径")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "导入地铁数据" }));
    expect(await screen.findByRole("progressbar", { name: "地铁数据导入进度" })).toHaveAttribute("value", "1");
    await user.click(screen.getByRole("button", { name: "取消导入" }));
    expect(await screen.findByText("导入已取消")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "导入地铁数据" }));
    await screen.findByText("地铁数据已就绪");
    await user.click(screen.getByRole("button", { name: "开始记录地铁行程" }));
    expect(state.metro_directory).toBe("/tmp/data");
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/journeys/new"));
    expect(state.progress.completed).toBe(true);
  });

  it("explains missing Java and waits for station indexing after service startup", async () => {
    const user = userEvent.setup(); show("/setup?step=rail");
    await user.click(await screen.findByRole("button", { name: "启动铁路服务" }));
    expect(within(await screen.findByRole("alert")).getByText("没有找到 Java 17 或更高版本")).toBeInTheDocument();
    await user.click(screen.getByText("高级设置：Java 与服务文件"));
    await user.type(screen.getByLabelText("Java 安装目录"), "/tmp/java");
    await user.click(screen.getByRole("button", { name: "重新检查" }));
    await waitFor(() => expect(screen.queryAllByText("没有找到 Java 17 或更高版本")).toHaveLength(0));
    await user.click(screen.getByRole("button", { name: "启动铁路服务" }));
    expect(await screen.findByText("路径服务已启动，还需准备车站索引")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "下一步：开始使用" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "导入车站索引" }));
    await screen.findByText("铁路数据已就绪");
    await user.click(screen.getByRole("button", { name: "下一步：开始使用" }));
    await user.click(await screen.findByRole("button", { name: "开始记录行程" }));
    await waitFor(() => expect(state.progress.completed).toBe(true));
  });

  it("offers recovery for offline services, blocked environment and failed progress saves", async () => {
    const user = userEvent.setup(); offline = true; environmentFailed = true; show();
    await screen.findByText("无法连接本地服务"); offline = false;
    await user.click(screen.getByRole("button", { name: "重新连接" }));
    expect(await screen.findByText("数据库需要升级")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一步：导入地铁数据" })).toBeDisabled();
    environmentFailed = false;
    await user.click(screen.getByRole("button", { name: "重新检查" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "下一步：导入地铁数据" })).toBeEnabled());
    saveFailed = true;
    await user.click(screen.getByRole("button", { name: "下一步：导入地铁数据" }));
    expect(await screen.findByText("进度保存暂时失败")).toBeInTheDocument();
    saveFailed = false;
    await user.click(screen.getByRole("button", { name: "稍后设置" }));
    await waitFor(() => expect(state.progress.dismissed).toBe(true));
  });

  it("keeps setup incomplete after a railway mismatch and supports skipping railway", async () => {
    const user = userEvent.setup(); railChecks = 1; railFailed = true; show("/setup?step=rail");
    await user.click(await screen.findByRole("button", { name: "启动铁路服务" }));
    expect(await screen.findByText("服务与所选图版本不一致")).toBeInTheDocument();
    await user.click(screen.getByText("故障诊断与日志"));
    expect(screen.getByText("/tmp/logs/rail-sidecar.log")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "跳过，先使用地铁" }));
    expect(await screen.findByRole("heading", { name: "还差一份线路数据" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始记录行程" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "继续准备数据" }));
    expect(await screen.findByRole("heading", { name: "导入地铁线路数据" })).toBeInTheDocument();
  });

  it.each([true, false])("routes new and existing installations without forcing an existing user through setup: %s", async (firstRun) => {
    state.should_show = firstRun;
    renderApp(<Routes><Route path="/" element={<SetupEntry />} /><Route path="/setup" element={<p>setup destination</p>} /><Route path="/journeys/new" element={<p>journey destination</p>} /></Routes>, "/");
    expect(await screen.findByText(firstRun ? "setup destination" : "journey destination")).toBeInTheDocument();
  });
});
