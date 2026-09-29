import { expect, test, type Page } from "@playwright/test";
import { initialSetupState, readyChecks, catalogFixture, idleCityDownload } from "../src/test/setupFixtures";
import type { SetupProgressPatch } from "../src/api/client";

async function mockSetup(page: Page) {
  const state = initialSetupState();
  let importAttempts = 0;
  let serviceReads = 0;
  let indexReads = 0;
  await page.route("**/api/v1/**", (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/data/city-packs/catalog") return route.fulfill({ json: catalogFixture });
    if (path === "/api/v1/data/city-packs/download") return route.fulfill({ json: idleCityDownload });
    if (path === "/api/v1/setup") {
      if (state.service.status === "starting" && ++serviceReads > 1) state.service.status = "ready";
      if (state.rail.status === "importing" && ++indexReads > 1) { state.rail.status = "ready"; state.rail.station_count = 48; }
      return route.fulfill({ json: state });
    }
    if (path === "/api/v1/setup/checks") return route.fulfill({ json: readyChecks });
    if (path === "/api/v1/setup/progress") {
      const patch = request.postDataJSON() as SetupProgressPatch;
      if (patch.step) state.progress.step = patch.step;
      if (patch.dismissed !== undefined && patch.dismissed !== null) state.progress.dismissed = patch.dismissed;
      if (patch.rail_skipped !== undefined && patch.rail_skipped !== null) state.progress.rail_skipped = patch.rail_skipped;
      if (patch.complete) state.progress.completed = true;
      if (patch.metro_directory) state.metro_directory = patch.metro_directory;
      state.should_show = !state.progress.dismissed && !state.progress.completed;
      return route.fulfill({ json: state.progress });
    }
    if (path === "/api/v1/data/imports") {
      state.metro = { ...state.metro, status: ++importAttempts === 1 ? "importing" : "ready", ready_available: importAttempts > 1, total_cities: 1, processed_cities: importAttempts > 1 ? 1 : 0, import_id: 7, cities: importAttempts > 1 ? 1 : 0, ready_lines: importAttempts > 1 ? 1 : 0 };
      return route.fulfill({ status: 202, json: { import_id: 7, status: "staging" } });
    }
    if (path === "/api/v1/data/imports/7/cancel") { state.metro.status = "cancelled"; return route.fulfill({ json: { import_id: 7, status: "cancelled" } }); }
    if (path === "/api/v1/setup/rail/check") return route.fulfill({ json: readyChecks });
    if (path === "/api/v1/setup/rail/start") { state.service.status = "starting"; state.rail.status = "not_configured"; state.rail.enabled = true; return route.fulfill({ status: 202, json: state.service }); }
    if (path === "/api/v1/rail/data/imports") { state.rail.status = "importing"; return route.fulfill({ status: 202, json: { import_id: 9, status: "staging" } }); }
    if (path === "/api/v1/data/status") return route.fulfill({ json: state.metro });
    if (path === "/api/v1/rail/data/status") return route.fulfill({ json: state.rail });
    if (path === "/api/v1/config/public") return route.fulfill({ json: { map: { tiles_enabled: false, tile_url: "", tile_attribution: "", max_zoom: 19, external_tiles: false } } });
    if (path === "/api/v1/cities") return route.fulfill({ json: [] });
    if (path === "/api/v1/data/quality") return route.fulfill({ json: { dataset_version_id: 1, ready_cities: 1, blocked_cities: 0, ready_lines: 1, blocked_lines: 0, ready_variants: 1, blocked_variants: 0, issues: [] } });
    return route.fulfill({ status: 404, json: { error: { message: "Unexpected fixture request" } } });
  });
  return state;
}

test("first launch resumes import progress and completes with metro only", async ({ page }) => {
  await mockSetup(page);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page).toHaveURL(/\/setup$/);
  await expect(page.getByRole("heading", { name: "先检查运行环境" })).toBeVisible();
  await page.getByRole("button", { name: "下一步：导入地铁数据" }).click();
  await page.getByText("高级：导入原始数据目录", { exact: true }).click();
  await page.getByLabel("地铁数据目录（本机绝对路径）").fill("/tmp/metro-data");
  await page.getByRole("button", { name: "导入地铁数据", exact: true }).click();
  await expect(page.getByRole("progressbar", { name: "地铁数据导入进度" })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("地铁数据目录（本机绝对路径）")).toHaveValue("/tmp/metro-data");
  await page.getByRole("button", { name: "取消导入" }).click();
  await expect(page.getByText("导入已取消")).toBeVisible();
  await page.getByRole("button", { name: "导入地铁数据", exact: true }).click();
  await expect(page.getByText("地铁数据已就绪")).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await page.getByRole("button", { name: "开始记录地铁行程" }).click();
  await expect(page).toHaveURL(/\/journeys\/new$/);
  await page.goto("/");
  await expect(page).toHaveURL(/\/journeys\/new$/);
  expect(errors).toEqual([]);
});

test("rail service startup is separate from index readiness", async ({ page }) => {
  await mockSetup(page);
  await page.goto("/setup?step=rail");
  await page.getByRole("button", { name: "启动铁路服务" }).click();
  await expect(page.getByRole("progressbar", { name: "铁路服务启动进度" })).toBeVisible();
  await expect(page.getByRole("button", { name: "导入车站索引" })).toBeVisible();
  await expect(page.getByRole("button", { name: "下一步：开始使用" })).toHaveCount(0);
  await page.getByRole("button", { name: "导入车站索引" }).click();
  await expect(page.getByText("铁路数据已就绪")).toBeVisible();
  await page.getByRole("button", { name: "下一步：开始使用" }).click();
  await expect(page.getByRole("button", { name: "开始记录行程" })).toBeEnabled();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
});

test("rail errors remain actionable and skipping does not fake readiness", async ({ page }) => {
  await mockSetup(page);
  await page.route("**/api/v1/setup/rail/check", (route) => route.fulfill({ json: {
    can_continue: false, checks: [{ id: "java", title: "Java 运行环境", status: "failed", detail: "没有找到 Java 17 或更高版本", remedy: "安装 Java 后重新检查，或在高级设置中填写 Java 目录。" }],
  } }));
  await page.goto("/setup?step=rail");
  await page.getByRole("button", { name: "启动铁路服务" }).click();
  await expect(page.getByRole("alert").getByText("没有找到 Java 17 或更高版本")).toBeVisible();
  await page.getByText("高级设置：Java 与服务文件").click();
  await expect(page.getByLabel("Java 安装目录")).toBeVisible();
  await page.getByRole("button", { name: "跳过，先使用地铁" }).click();
  await expect(page.getByRole("heading", { name: "还差一份线路数据" })).toBeVisible();
  await expect(page.getByRole("button", { name: "开始记录行程" })).toBeDisabled();
  await page.getByRole("button", { name: "继续准备数据" }).click();
  await expect(page.getByRole("heading", { name: "导入地铁线路数据" })).toBeVisible();
});

test("optional railway components retry, survive navigation and do not fake data readiness", async ({ page }) => {
  const state = await mockSetup(page);
  state.rail_config.jar_path = null;
  state.components = { status: "idle", downloaded_bytes: 0, total_bytes: 96000000, message: null, jar_path: null, java_home: null };
  let attempts = 0;
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
  await page.route("**/api/v1/setup/rail/components", async (route) => {
    expect(route.request().postDataJSON()).toEqual({ install: true });
    attempts += 1;
    state.components.status = attempts === 1 ? "failed" : "downloading";
    state.components.downloaded_bytes = attempts === 1 ? 0 : 48000000;
    state.components.message = attempts === 1 ? "下载未完成，请重试以继续下载。" : "正在下载铁路引擎和专用 Java";
    await route.fulfill({ status: 202, json: state.components });
  });
  await page.goto("/setup?step=rail");
  await expect(page).toHaveTitle(/Transit2Fog/);
  await expect(page.getByRole("heading", { name: "准备铁路服务" })).toBeVisible();
  await page.getByRole("button", { name: "下载并准备铁路组件" }).click();
  await expect(page.getByRole("alert").getByText("下载未完成，请重试以继续下载。")).toBeVisible();
  await page.getByRole("button", { name: "重试组件下载" }).click();
  await expect(page.getByRole("progressbar", { name: "铁路组件下载进度" })).toHaveAttribute("value", "48000000");
  await expect(page.getByRole("button", { name: "启动铁路服务" })).toBeDisabled();
  await page.reload();
  await expect(page.getByRole("progressbar", { name: "铁路组件下载进度" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  state.components.status = "ready";
  state.components.jar_path = "/tmp/components/openrailrouting.jar";
  state.components.java_home = "/tmp/components/java";
  await expect(page.getByText("铁路组件已就绪", { exact: true })).toBeVisible();
  await expect(page.getByText("铁路数据已就绪", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "启动铁路服务" })).toBeEnabled();
  await page.getByText("高级设置：Java 与服务文件").click();
  await expect(page.getByLabel("Java 安装目录")).toHaveValue("");
  await expect(page.getByLabel("铁路服务 JAR 文件")).toHaveValue("");
  // Empty overrides keep auto-discovery version-aware on future upgrades.
  await page.getByRole("button", { name: "跳过，先使用地铁" }).click();
  await expect(page.getByRole("heading", { name: "还差一份线路数据" })).toBeVisible();
  expect(attempts).toBe(2);
  expect(errors).toEqual([]);
});

test("light edition installs a city pack after preview and hides raw GIS controls", async ({ page }) => {
  const state = await mockSetup(page);
  state.raw_import_available = false;
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let attempts = 0;
  await page.route("**/api/v1/data/city-packs/inspect", async (route) => {
    attempts += 1;
    if (attempts === 1) return route.fulfill({ status: 422, json: { error: { code: "invalid_city_pack", message: "城市包校验失败，原有数据已保留。" } } });
    return route.fulfill({ json: {
      package_id: "a".repeat(64), lines: 2, stations: 20, ready_variants: 3, blocked_variants: 1,
      manifest: { format: "transit2fog-city-v1", city_code: "310000", city_name: "上海", network_sha256: "b".repeat(64),
        source: { name: "CPTOND", version: "2025-snapshot", url: "https://example.org", license: "CC BY 4.0", captured_at: "2025-06", checksum: "source-checksum", importer: "cptond-v2.3", attribution: "测试来源署名，仅供验收" } },
    } });
  });
  await page.route("**/api/v1/data/city-packs/install", async (route) => {
    expect(route.request().postDataJSON()).toEqual({ package_id: "a".repeat(64) });
    state.metro = { ...state.metro, status: "ready", ready_available: true, cities: 1, ready_lines: 2, processed_cities: 1, total_cities: 1 };
    return route.fulfill({ json: { dataset_id: 8, status: "ready" } });
  });
  await page.goto("/setup?step=metro");
  await expect(page.getByLabel("地铁数据目录（本机绝对路径）")).toHaveCount(0);
  await page.getByText("导入本地城市包（离线）", { exact: true }).click();
  await page.getByLabel("选择城市数据包").setInputFiles({name: "bad.t2fcity", mimeType: "application/zip", buffer: Buffer.from("bad")});
  await expect(page.getByRole("alert").getByText("城市包校验失败，原有数据已保留。")).toBeVisible();
  await page.getByLabel("选择城市数据包").setInputFiles({name: "shanghai.t2fcity", mimeType: "application/zip", buffer: Buffer.from("fixture")});
  await expect(page.getByText("上海 · 2025-06", { exact: true })).toBeVisible();
  await page.getByText("来源、许可与版本", { exact: true }).click();
  await expect(page.getByText("测试来源署名，仅供验收")).toBeVisible();
  await expect(page.getByText("地铁数据已就绪", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "安装城市数据", exact: true }).click();
  await expect(page.getByText("地铁数据已就绪", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "开始记录地铁行程" })).toBeVisible();
  await page.reload();
  await expect(page.getByText("地铁数据已就绪", { exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  expect(errors).toEqual([]);
});

test("online city download retries, survives reload and offers direct metro entry", async ({ page }) => {
  const state = await mockSetup(page);
  state.raw_import_available = false;
  let phase = "idle";
  let attempts = 0;
  let reads = 0;
  await page.route("**/api/v1/data/city-packs/download", async (route) => {
    if (route.request().method() === "POST") {
      expect(route.request().postDataJSON()).toEqual({ city_code: "021" });
      attempts += 1;
      phase = attempts === 1 ? "failed" : "downloading";
    } else if (phase === "downloading" && ++reads > 3) {
      phase = "ready";
      state.metro = { ...state.metro, status: "ready", ready_available: true, cities: 1, ready_lines: 66 };
    }
    return route.fulfill({ status: route.request().method() === "POST" ? 202 : 200, json: { ...idleCityDownload, status: phase, city_code: "021", city_name: "上海", total_bytes: 692890, downloaded_bytes: phase === "ready" ? 692890 : 300000, dataset_id: phase === "ready" ? 9 : null, message: phase === "failed" ? "网络不可用，请重试。" : phase === "ready" ? "上海已就绪，可以开始记录行程。" : "正在下载…" } });
  });
  await page.route("**/api/v1/cities", (route) => route.fulfill({ json: state.metro.ready_available ? [{id:7, name_cn:"上海", name_en:"Shanghai", city_code:"021", checksum:catalogFixture.packages[0].sha256, center:[121.4,31.2], bbox:[121,31,122,32]}] : [] }));
  await page.route("**/api/v1/cities/7/lines", (route) => route.fulfill({ json: [] }));
  await page.goto("/setup?step=metro");
  await page.getByLabel("选择要下载的城市").selectOption("021");
  await page.getByRole("button", { name: "下载并安装上海" }).click();
  await expect(page.getByText("网络不可用，请重试。")).toBeVisible();
  await page.getByRole("button", { name: "重试城市下载" }).click();
  await expect(page.getByRole("progressbar", { name: "城市数据下载进度" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("progressbar", { name: "城市数据下载进度" })).toBeVisible();
  await expect(page.getByText("地铁数据已就绪", { exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await page.getByRole("button", { name: "记录该城市行程 →", exact: true }).click();
  await expect(page).toHaveURL(/\/journeys\/new\?city=7$/);
  expect(state.progress.completed).toBe(true);
  expect(attempts).toBe(2);
});
