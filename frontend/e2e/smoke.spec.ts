import { expect, test, type Page } from "@playwright/test";

const journey = {
  id: 7,
  journey_code: "J-20260820-001",
  traveled_at: "2026-08-20",
  source_type: "manual",
  note: "晚高峰",
  created_at: "2026-08-20T00:00:00Z",
  updated_at: "2026-08-20T00:00:00Z",
  distance_m: 18_342.7,
  legs: [
    {
      id: 70,
      leg_no: 1,
      transport_mode: "metro",
      dataset_version_id: 1,
      rail_dataset_version_id: null,
      graph_version: null,
      city_id: 1,
      city_name: "上海",
      line_id: 2,
      line_name: "2号线",
      route_variant_id: 18,
      start_station_id: 101,
      start_station_name: "虹桥火车站",
      end_station_id: 132,
      end_station_name: "人民广场",
      direction: "auto",
      resolution_status: "resolved",
      candidate_digest: "sha256:test",
      edge_ids: [501],
      reversed_edges: [false],
      distance_m: 18_342.7,
    },
  ],
};

const railJourney = {
  ...journey,
  id: 8,
  journey_code: "R-20260820-001",
  distance_m: 159_000,
  legs: [
    {
      id: 80,
      leg_no: 1,
      transport_mode: "rail",
      dataset_version_id: null,
      rail_dataset_version_id: 9,
      graph_version: "yangtze-20260815-r0.1",
      city_id: null,
      city_name: null,
      line_id: null,
      line_name: null,
      route_variant_id: null,
      start_station_id: 801,
      start_station_name: "上海虹桥",
      end_station_id: 802,
      end_station_name: "杭州东",
      travel_date: "2026-08-20",
      train_no: "G1",
      train_type: "G",
      timetable_provider: "manual",
      routing_profile: "china_high_speed",
      scoring_version: "2026-08-21-r0.2",
      route_hint: null,
      score_details: [],
      warnings: [],
      via_station_ids: [],
      osm_way_ids: [9901],
      direction: "china_high_speed",
      resolution_status: "resolved",
      candidate_digest: `sha256:${"b".repeat(64)}`,
      edge_ids: [901],
      reversed_edges: [false],
      distance_m: 159_000,
    },
  ],
};

type MockJourney = Omit<typeof journey, "traveled_at" | "note"> & {
  traveled_at: string | null;
  note: string | null;
};

const candidate = {
  candidate_id: "cand_test",
  digest: "sha256:test",
  dataset_version_id: 1,
  route_variant_id: 18,
  line_name: "2号线",
  direction_name: "正向",
  distance_m: 18_342.7,
  station_count: 13,
  station_ids: [101, 132],
  edge_ids: [501],
  reversed_edges: [false],
  geometry: {
    type: "LineString",
    coordinates: [
      [121.312, 31.194],
      [121.381, 31.209],
      [121.475, 31.231],
    ],
  },
  warnings: [],
};

const railRecomputeCandidate = {
  mode: "rail",
  candidate_id: "rail_cand_recompute",
  digest: `sha256:${"c".repeat(64)}`,
  rail_dataset_version_id: 10,
  graph_version: "china-20260815-r3.1",
  profile_version: "2026-08-21-r0.1",
  scoring_version: "2026-08-21-r0.2",
  routing_profile: "china_high_speed",
  distance_m: 159_500,
  duration_ms: 3_600_000,
  station_count: 2,
  station_ids: [1801, 1802],
  geometry: {
    type: "LineString",
    coordinates: [
      [121.327, 31.2],
      [120.212, 30.29],
    ],
  },
  way_ranges: [{ start_index: 0, end_index: 1, osm_way_id: 19901 }],
  score: 0.97,
  score_details: [],
  warnings: [],
  can_commit: true,
};

async function mockReadyShell(page: Page) {
  await page.route("**/api/v1/cities", route => route.fulfill({ json: [] }));
  await page.route("**/api/v1/config/public", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: {
        map: {
          tiles_enabled: true,
          tile_url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
          tile_attribution: "© OpenStreetMap contributors",
          max_zoom: 19,
          external_tiles: true,
        },
      },
    }),
  );
  await page.route("**/api/v1/data/status", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: {
        status: "ready",
        dataset: "CPTOND-2025",
        captured_at: "2025-06",
        license: "CC BY 4.0",
        cities: 46,
        imported_at: "2026-08-20T00:00:00Z",
        quality_status: "ready",
      },
    }),
  );
  await page.route("**/api/v1/rail/data/status", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: {
        status: "disabled",
        enabled: false,
        sidecar_available: false,
        rail_dataset_version_id: null,
        dataset_status: null,
        station_count: 0,
        graph_version: null,
        profile_version: null,
        sidecar_graph_version: null,
        sidecar_profile_version: null,
        sidecar_pbf_checksum: null,
        pbf_checksum: null,
        source_url: null,
        source_timestamp: null,
        extract_region: null,
        license: null,
        profiles: [],
        bbox: null,
        error_code: null,
        error_message: null,
      },
    }),
  );
  await page.route("**/api/v1/data/quality", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: {
        dataset_version_id: 1,
        ready_cities: 46,
        blocked_cities: 0,
        ready_lines: 992,
        blocked_lines: 0,
        ready_variants: 992,
        blocked_variants: 0,
        issues: [],
      },
    }),
  );
  await page.route("**/api/v1/journeys/filters", (route) => route.fulfill({ json: {
    cities: [{ id: 1, name: "上海" }], lines: [{ id: 2, name: "2号线", city_id: 1 }],
  }}));
  await page.route("https://tile.openstreetmap.org/**", (route) => route.abort());
}

async function mockJourneyNetwork(page: Page) {
  await page.route("**/api/v1/cities/1/map?line_id=2", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: {
        city_id: 1,
        dataset_version_id: 1,
        bbox: [121.312, 31.194, 121.475, 31.231],
        lines: {
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              geometry: {
                type: "LineString",
                coordinates: candidate.geometry.coordinates,
              },
              properties: { name_cn: "2号线", display_color: "#079aa4" },
            },
          ],
        },
        stations: {
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              geometry: { type: "Point", coordinates: [121.312, 31.194] },
              properties: { station_id: 101, name_cn: "虹桥火车站" },
            },
            {
              type: "Feature",
              geometry: { type: "Point", coordinates: [121.475, 31.231] },
              properties: { station_id: 132, name_cn: "人民广场" },
            },
          ],
        },
      },
    }),
  );
  await page.route("**/api/v1/cities", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: [
        {
          id: 1,
          name_cn: "上海",
          name_en: "Shanghai",
          center: [121.47, 31.23],
          bbox: [121.312, 31.194, 121.475, 31.231],
        },
      ],
    }),
  );
  await page.route("**/api/v1/cities/1/lines", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: [
        {
          id: 2,
          city_id: 1,
          name_cn: "2号线",
          name_en: "Line 2",
          display_color: "#079aa4",
        },
      ],
    }),
  );
  await page.route("**/api/v1/lines/2/stations", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: [
        {
          id: 101,
          city_id: 1,
          name_cn: "虹桥火车站",
          name_en: "Hongqiao Railway Station",
          lon: 121.312,
          lat: 31.194,
        },
        {
          id: 132,
          city_id: 1,
          name_cn: "人民广场",
          name_en: "People's Square",
          lon: 121.475,
          lat: 31.231,
        },
      ],
    }),
  );
  await page.route("**/api/v1/stations/search?**", (route) => {
    const query = new URL(route.request().url()).searchParams.get("q");
    return route.fulfill({
      contentType: "application/json",
      json:
        query === "renmin"
          ? [
              {
                id: 132,
                city_id: 1,
                name_cn: "人民广场",
                name_en: "People's Square",
                lon: 121.475,
                lat: 31.231,
              },
            ]
          : [],
    });
  });
  await page.route("**/api/v1/paths/preview", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: { status: "resolved", candidates: [candidate] },
    }),
  );
}

test.beforeEach(async ({ page }) => {
  await mockReadyShell(page);
});

test("disabled railway data gives feedback while facts remain editable", async ({ page }) => {
  await page.goto("/journeys/new");
  await page.getByRole("tab", { name: "铁路 / 高铁" }).click();

  const date = page.getByLabel("乘坐日期（必填）");
  const trainNo = page.getByLabel("车次（建议）");
  const trainType = page.getByLabel("车型");
  const start = page.getByRole("combobox", { name: "上车站" });
  await expect(date).toBeEnabled();
  await expect(trainNo).toBeEnabled();
  await expect(trainType).toBeEnabled();
  await expect(start).toBeEnabled();

  await date.fill("2026-08-21");
  await trainNo.fill("G1");
  await trainType.selectOption("D");
  await start.fill("北京南");

  await expect(page.getByText("铁路功能暂不可用")).toBeVisible();
  await expect(
    page.getByRole("status").filter({ hasText: "当前本地服务未启用铁路功能" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "铁路数据就绪后可预览" })).toBeDisabled();
  await page.getByRole("link", { name: "查看铁路设置" }).click();
  await expect(page).toHaveURL(/\/settings\/data$/);
  await expect(page.getByRole("heading", { name: "数据与设置" })).toBeVisible();
});

test("real-map journey can be previewed and saved", async ({ page }) => {
  await mockJourneyNetwork(page);
  let savedBody: Record<string, unknown> | undefined;
  await page.route("**/api/v1/journeys", async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback();
      return;
    }
    savedBody = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({ contentType: "application/json", json: journey });
  });
  await page.route("**/api/v1/exports/preview", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: {
        preview_token: `sha256:${"a".repeat(64)}`,
        journey_count: 1,
        edge_count: 1,
        unique_edge_count: 1,
        distance_m: 18_342.7,
        track_count: 1,
        segment_count: 1,
        dataset_version_ids: [1],
        rail_dataset_version_ids: [],
        rail_graph_versions: [],
        blocking_errors: [],
        warnings: [],
      },
    }),
  );
  await page.route("**/api/v1/exports/gpx", (route) =>
    route.fulfill({
      body: '<?xml version="1.0"?><gpx version="1.1" />',
      contentType: "application/gpx+xml",
      headers: { "Content-Disposition": 'attachment; filename="direct.gpx"' },
    }),
  );

  await page.goto("/journeys/new");
  await expect(page.getByRole("heading", { name: "添加一段真实乘坐记录" })).toBeVisible();
  await expect(page.getByRole("region", { name: "真实地理底图与已导入地铁线路" })).toBeVisible();
  await expect(page.locator(".leaflet-tile-pane")).toBeAttached();
  await expect(page.locator(".leaflet-overlay-pane path.leaflet-interactive")).toHaveCount(3);

  const startStation = page.getByRole("combobox", { name: "起点站" });
  const endStation = page.getByRole("combobox", { name: "终点站" });
  await startStation.click();
  await startStation.fill("renmin");
  await expect(
    page.getByRole("listbox").getByRole("option", { name: /人民广场/ }),
  ).toBeVisible();
  await startStation.press("Enter");
  await endStation.click();
  await endStation.fill("虹桥");
  await expect(
    page.getByRole("listbox").getByRole("option", { name: /虹桥火车站/ }),
  ).toBeVisible();
  await endStation.press("Enter");

  await page.getByRole("button", { name: "预览路径" }).click();
  await expect(page.getByRole("heading", { name: "候选路径" })).toBeVisible();
  await expect(page.getByText("2号线 · 人民广场 → 虹桥火车站")).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出 GPX" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("direct.gpx");
  await expect(page.getByRole("button", { name: "已保存" })).toBeVisible();
  expect(savedBody).toMatchObject({
    source_type: "manual",
    legs: [{ candidate_id: "cand_test", candidate_digest: "sha256:test" }],
  });
});

test("map station clicks save a map-sourced journey", async ({ page }) => {
  await mockJourneyNetwork(page);
  let savedBody: {
    source_type?: string;
    legs?: { start_station_id?: number; end_station_id?: number }[];
  } | undefined;
  await page.route("**/api/v1/journeys", async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback();
      return;
    }
    savedBody = route.request().postDataJSON() as typeof savedBody;
    await route.fulfill({ contentType: "application/json", json: journey });
  });

  await page.goto("/journeys/new");
  const stationMarkers = page.locator('.leaflet-overlay-pane path[fill="#ffffff"]');
  await expect(stationMarkers).toHaveCount(2);
  await stationMarkers.nth(1).dispatchEvent("click");
  await expect(page.getByRole("combobox", { name: "起点站", exact: true })).toHaveValue("人民广场");
  await page.locator('.leaflet-overlay-pane path[fill="#ffffff"]').nth(0).dispatchEvent("click");
  await expect(page.getByRole("combobox", { name: "起点站", exact: true })).toHaveValue("人民广场");
  await expect(page.getByRole("combobox", { name: "终点站", exact: true })).toHaveValue("虹桥火车站");
  await page.getByRole("button", { name: "预览路径" }).click();
  await page.getByRole("button", { name: "保存行程" }).click();
  await expect.poll(() => savedBody?.source_type).toBe("map");
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
  expect(savedBody?.legs?.[0]?.start_station_id).not.toBe(
    savedBody?.legs?.[0]?.end_station_id,
  );
});

test("unspecified line transfer candidate is confirmed and saved as two legs", async ({ page }) => {
  await mockJourneyNetwork(page);
  const transferCandidate = {
    ...candidate,
    candidate_id: "multi_transfer",
    digest: "sha256:multi",
    route_variant_id: null,
    line_name: "1号线 → 2号线",
    direction_name: "1 次换乘",
    station_count: 3,
    station_ids: [101, 132, 160],
    edge_ids: [501, 601],
    warnings: [
      {
        code: "unspecified_line_requires_confirmation",
        message: "未指定线路的换乘候选必须人工确认。",
      },
    ],
    legs: [
      {
        candidate_id: "cand_leg_1",
        digest: "sha256:leg1",
        dataset_version_id: 1,
        line_id: 2,
        route_variant_id: 18,
        line_name: "1号线",
        direction_name: "正向",
        distance_m: 10_000,
        start_station_id: 101,
        end_station_id: 132,
        station_ids: [101, 132],
        edge_ids: [501],
        reversed_edges: [false],
        warnings: [],
      },
      {
        candidate_id: "cand_leg_2",
        digest: "sha256:leg2",
        dataset_version_id: 1,
        line_id: 3,
        route_variant_id: 19,
        line_name: "2号线",
        direction_name: "正向",
        distance_m: 8_342.7,
        start_station_id: 132,
        end_station_id: 160,
        station_ids: [132, 160],
        edge_ids: [601],
        reversed_edges: [false],
        warnings: [],
      },
    ],
  };
  await page.route("**/api/v1/cities/1/stations", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: [
        { id: 101, city_id: 1, name_cn: "虹桥火车站", name_en: null, lon: 121.312, lat: 31.194 },
        { id: 132, city_id: 1, name_cn: "人民广场", name_en: null, lon: 121.475, lat: 31.231 },
        { id: 160, city_id: 1, name_cn: "浦东机场", name_en: null, lon: 121.8, lat: 31.15 },
      ],
    }),
  );
  await page.route("**/api/v1/cities/1/map", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: {
        city_id: 1,
        dataset_version_id: 1,
        bbox: [121.312, 31.15, 121.8, 31.231],
        lines: {
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              geometry: transferCandidate.geometry,
              properties: { name_cn: "换乘候选", display_color: "#079aa4" },
            },
          ],
        },
        stations: { type: "FeatureCollection", features: [] },
      },
    }),
  );
  let previewBody: { via_station_ids?: number[] } | undefined;
  await page.route("**/api/v1/paths/preview", (route) => {
    previewBody = route.request().postDataJSON() as typeof previewBody;
    return route.fulfill({
      contentType: "application/json",
      json: { status: "needs_review", candidates: [transferCandidate] },
    });
  });
  let savedBody: { source_type?: string; legs?: unknown[] } | undefined;
  await page.route("**/api/v1/journeys", async (route) => {
    if (route.request().method() !== "POST") {
      await route.fallback();
      return;
    }
    savedBody = route.request().postDataJSON() as typeof savedBody;
    await route.fulfill({ contentType: "application/json", json: journey });
  });

  await page.goto("/journeys/new");
  await page.locator('select[name="line"]').selectOption("auto");
  const viaStation = page.getByRole("combobox", { name: "途经站（可选）" });
  await expect(viaStation).toBeEnabled();
  await viaStation.click();
  await viaStation.fill("renmin");
  await expect(
    page.getByRole("listbox").getByRole("option", { name: /人民广场/ }),
  ).toBeVisible();
  await viaStation.press("Enter");
  await page.getByRole("button", { name: "预览路径" }).click();
  expect(previewBody?.via_station_ids).toEqual([132]);
  await expect(page.getByText("1号线 → 2号线 · 虹桥火车站 → 浦东机场")).toBeVisible();
  await page.getByRole("button", { name: "保存行程" }).click();
  await expect.poll(() => savedBody?.legs?.length).toBe(2);
  expect(savedBody?.source_type).toBe("manual");
});

test("journey list supports filtering and metadata editing", async ({ page }) => {
  let currentJourney: MockJourney = { ...journey };
  await page.route("**/api/v1/journeys**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === "/api/v1/journeys") {
      await route.fulfill({
        contentType: "application/json",
        json: url.searchParams.get("q") ? { items: [], total: 0 } : { items: [currentJourney], total: 1 },
      });
      return;
    }
    if (request.method() === "GET" && url.pathname === "/api/v1/journeys/7") {
      await route.fulfill({ json: currentJourney }); return;
    }
    if (request.method() === "PATCH" && url.pathname === "/api/v1/journeys/7") {
      const input = request.postDataJSON() as {
        traveled_at?: string | null;
        note?: string | null;
      };
      currentJourney = { ...currentJourney, ...input };
      await route.fulfill({ contentType: "application/json", json: currentJourney });
      return;
    }
    await route.fallback();
  });

  await page.goto("/journeys");
  await expect(page.getByText("上海 · 2号线 · 虹桥火车站 → 人民广场")).toBeVisible();
  await page.getByText("查看详情").click();
  await expect(page.getByText(/数据版本 1 · 1 个区间/)).toBeVisible();
  await page.getByPlaceholder("按城市、线路、站点、编号或备注筛选").fill("不存在");
  await expect(page.getByText("没有符合筛选条件的行程。")).toBeVisible();
  await page.getByPlaceholder("按城市、线路、站点、编号或备注筛选").fill("");
  await page.getByRole("button", { name: "编辑" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page.getByRole("button", { name: "编辑" })).toBeFocused();
  await page.getByRole("button", { name: "编辑" }).click();
  await page.getByRole("dialog").getByLabel("备注").fill("机场接驳");
  await page.getByRole("button", { name: "保存修改" }).click();
  await expect(page.getByText(/机场接驳/)).toBeVisible();
});

test("rail journey recompute confirms a new immutable candidate", async ({ page }) => {
  let recomputeBody: Record<string, unknown> | undefined;
  await page.route("**/api/v1/journeys**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === "/api/v1/journeys") {
      await route.fulfill({
        contentType: "application/json",
        json: { items: [railJourney], total: 1 },
      });
      return;
    }
    if (
      request.method() === "POST" &&
      url.pathname === "/api/v1/journeys/8/rail-recompute/preview"
    ) {
      await route.fulfill({
        contentType: "application/json",
        json: {
          journey_id: 8,
          target_graph_version: "china-20260815-r3.1",
          target_profile_version: "2026-08-21-r0.1",
          legs: [
            {
              leg_no: 1,
              source_graph_version: "yangtze-20260815-r0.1",
              target_graph_version: "china-20260815-r3.1",
              station_names: ["上海虹桥", "杭州东"],
              status: "needs_review",
              candidates: [railRecomputeCandidate],
            },
          ],
        },
      });
      return;
    }
    if (
      request.method() === "POST" &&
      url.pathname === "/api/v1/journeys/8/rail-recompute"
    ) {
      recomputeBody = request.postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        contentType: "application/json",
        json: {
          ...railJourney,
          id: 9,
          journey_code: "R-20260820-002",
          legs: [
            {
              ...railJourney.legs[0],
              graph_version: "china-20260815-r3.1",
              candidate_digest: railRecomputeCandidate.digest,
            },
          ],
        },
      });
      return;
    }
    await route.fallback();
  });

  await page.goto("/journeys");
  await page.getByRole("button", { name: "重算铁路" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByText("yangtze-20260815-r0.1 → china-20260815-r3.1"),
  ).toBeVisible();
  await expect(dialog.getByText(/评分 97%/)).toBeVisible();
  const dialogBox = await dialog.boundingBox();
  const viewport = page.viewportSize();
  expect(dialogBox).not.toBeNull();
  expect(viewport).not.toBeNull();
  if (dialogBox && viewport) {
    expect(dialogBox.x).toBeGreaterThanOrEqual(0);
    expect(dialogBox.y).toBeGreaterThanOrEqual(0);
    expect(dialogBox.x + dialogBox.width).toBeLessThanOrEqual(viewport.width);
    expect(dialogBox.y + dialogBox.height).toBeLessThanOrEqual(viewport.height);
  }
  await dialog.getByRole("button", { name: "确认并创建新行程" }).click();
  await expect(dialog).toBeHidden();
  await expect.poll(() => recomputeBody).toMatchObject({
    target_graph_version: "china-20260815-r3.1",
    selections: [
      {
        leg_no: 1,
        candidate_id: "rail_cand_recompute",
        candidate_digest: railRecomputeCandidate.digest,
      },
    ],
  });
});

test("rail editor and graph comparison are usable", async ({ page }) => {
  await mockJourneyNetwork(page);
  await page.route("**/api/v1/rail/data/status", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: {
        status: "ready",
        enabled: true,
        sidecar_available: true,
        rail_dataset_version_id: 10,
        dataset_status: "ready",
        station_count: 18_490,
        graph_version: "china-20260815-r3.1",
        profile_version: "2026-08-21-r0.1",
        sidecar_graph_version: "china-20260815-r3.1",
        sidecar_profile_version: "2026-08-21-r0.1",
        sidecar_pbf_checksum: "checksum",
        pbf_checksum: "checksum",
        source_url: "https://download.geofabrik.de/asia/china.html",
        source_timestamp: "2026-08-15",
        extract_region: "China",
        license: "ODbL-1.0",
        profiles: ["china_high_speed", "china_emu", "china_conventional"],
        bbox: [69, 18, 135, 54],
        error_code: null,
        error_message: null,
      },
    }),
  );
  await page.route("**/api/v1/rail/data/compare?**", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: {
        from_graph_version: "yangtze-20260815-r0.1",
        to_graph_version: "china-20260815-r3.1",
        from_station_count: 2_400,
        to_station_count: 18_490,
        added_station_count: 16_100,
        removed_station_count: 10,
        changed_station_count: 42,
        unchanged_station_count: 2_348,
        affected_journey_count: 3,
        samples: [],
      },
    }),
  );

  await page.goto("/journeys/new");
  await page.getByRole("tab", { name: "铁路 / 高铁" }).click();
  await expect(
    page.getByRole("heading", { name: "添加一段真实铁路乘坐记录" }),
  ).toBeVisible();
  await expect(page.getByRole("combobox", { name: "上车站" })).toBeVisible();
  await page.goto("/settings/data");
  await page.getByText("比较铁路图版本").click();
  await page.getByLabel("原图版本").fill("yangtze-20260815-r0.1");
  await page.getByRole("button", { name: "查看版本差异" }).click();
  await expect(page.getByText("16100")).toBeVisible();
  await expect(page.getByText("3", { exact: true })).toBeVisible();
});

test("first setup shows persistent import progress and can cancel after refresh", async ({ page }) => {
  const baseStatus = {
    import_id: null as number | null,
    dataset: null as string | null,
    captured_at: null,
    license: null,
    source_url: null,
    checksum: null as string | null,
    importer_schema_version: null,
    cities: 0,
    route_count: 0,
    stop_count: 0,
    total_cities: 0,
    processed_cities: 0,
    ready_lines: 0,
    blocked_lines: 0,
    imported_at: null,
    completed_at: null,
    error_code: null as string | null,
    error_message: null as string | null,
    quality_status: "not_available",
  };
  let dataStatus: Record<string, unknown> = {
    ...baseStatus,
    status: "not_configured",
  };
  await page.route("**/api/v1/data/status", (route) =>
    route.fulfill({ contentType: "application/json", json: dataStatus }),
  );
  await page.route("**/api/v1/data/imports**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "POST" && url.pathname === "/api/v1/data/imports") {
      dataStatus = {
        ...baseStatus,
        status: "importing",
        import_id: 44,
        dataset: "CPTOND-v2",
        checksum: "abcdef1234567890",
        route_count: 80,
        stop_count: 1200,
        total_cities: 3,
        processed_cities: 1,
        ready_lines: 8,
        quality_status: "checking",
      };
      await route.fulfill({
        contentType: "application/json",
        json: {
          import_id: 44,
          status: "staging",
          route_count: 80,
          stop_count: 1200,
          checksum: "abcdef1234567890",
          total_cities: 0,
          processed_cities: 0,
          ready_lines: 0,
          blocked_lines: 0,
          error_code: null,
          error_message: null,
        },
      });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/v1/data/imports/44/cancel") {
      dataStatus = {
        ...dataStatus,
        status: "cancelled",
        error_code: "import_cancelled",
        error_message: "用户取消了数据导入",
        quality_status: "blocked",
      };
      await route.fulfill({
        contentType: "application/json",
        json: { import_id: 44, status: "cancelled" },
      });
      return;
    }
    await route.fallback();
  });

  await page.goto("/settings/data");
  await expect(
    page
      .getByRole("region", { name: "CPTOND 地铁数据" })
      .getByText("尚未导入地铁数据"),
  ).toBeVisible();
  await page.getByLabel("地铁数据目录（本机绝对路径）").fill("/data/cptond");
  await page.getByRole("button", { name: "导入数据目录" }).click();
  await expect(page.getByText("已处理 1 / 3 个城市")).toBeVisible();

  await page.reload();
  await expect(page.getByText("已处理 1 / 3 个城市")).toBeVisible();
  await page.getByRole("button", { name: "取消导入" }).click();
  await expect(page.getByText("上次导入已取消，可安全重新开始")).toBeVisible();
  await expect(page.getByText(/用户取消了数据导入/)).toBeVisible();
});

test("CSV review exposes ambiguous candidates before commit", async ({ page }) => {
  let selectedCandidateId: string | null = null;
  let repairedNote: string | undefined;
  let committed = false;
  const batch = () => ({
    id: 9,
    filename: "journeys.csv",
    encoding: "utf-8",
    total_rows: 51,
    resolved_rows: selectedCandidateId ? 51 : 0,
    review_rows: selectedCandidateId ? 0 : 51,
    failed_rows: 0,
    status: committed ? "committed" : "ready_for_review",
    created_at: "2026-08-20T00:00:00Z",
    committed_at: committed ? "2026-08-20T01:00:00Z" : null,
  });
  const importRow = (rowNo = 1) => ({
    id: rowNo === 1 ? 91 : 141,
    row_no: rowNo,
    raw: {},
    normalized: {
      journey_id: "A-1",
      city: "上海",
      line: "2号线",
      start_station: "虹桥火车站",
      end_station: "人民广场",
      direction: "",
      via_station: "",
      traveled_at: "2026-08-20",
      note: repairedNote ?? "",
    },
    resolution_status: committed
      ? "committed"
      : selectedCandidateId
        ? "resolved"
        : "needs_review",
    matched_city_id: 1,
    matched_line_id: 2,
    matched_start_station_id: 101,
    matched_end_station_id: 132,
    selected_candidate_id: selectedCandidateId,
    candidates: [candidate],
    error_code: null,
    error_message: null,
  });
  await page.route("**/api/v1/import-batches**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "POST" && url.pathname === "/api/v1/import-batches") {
      await route.fulfill({ contentType: "application/json", json: batch() });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/v1/import-batches/9/commit") {
      committed = true;
      await route.fulfill({ contentType: "application/json", json: batch() });
      return;
    }
    if (request.method() === "GET" && url.pathname === "/api/v1/import-batches/9") {
      await route.fulfill({ contentType: "application/json", json: batch() });
      return;
    }
    if (request.method() === "GET" && url.pathname === "/api/v1/import-batches/9/rows") {
      const offset = Number(url.searchParams.get("offset") ?? 0);
      await route.fulfill({
        contentType: "application/json",
        json: { items: [importRow(offset === 50 ? 51 : 1)], total: 51 },
      });
      return;
    }
    if (request.method() === "PATCH" && url.pathname === "/api/v1/import-batches/9/rows/91") {
      const input = request.postDataJSON() as {
        selected_candidate_id?: string | null;
        note?: string;
      };
      if ("selected_candidate_id" in input) {
        selectedCandidateId = input.selected_candidate_id ?? null;
      }
      if (input.note !== undefined) repairedNote = input.note;
      await route.fulfill({ contentType: "application/json", json: importRow() });
      return;
    }
    await route.fallback();
  });

  await page.goto("/imports/csv");
  await page.locator('input[type="file"]').setInputFiles({
    name: "journeys.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("city,line,start_station,end_station\n上海,2号线,虹桥火车站,人民广场"),
  });
  await expect(page.getByText("需人工确认")).toBeVisible();
  await page.getByRole("button", { name: "修复" }).click();
  await page.getByRole("dialog").getByLabel("note").fill("已人工核对");
  await page.getByRole("button", { name: "重新解析" }).click();
  await expect.poll(() => repairedNote).toBe("已人工核对");
  await page.getByLabel("第 1 行候选").selectOption("cand_test");
  await expect.poll(() => selectedCandidateId).toBe("cand_test");
  const commitButton = page.getByRole("button", { name: "提交全部已审核行" });
  await expect(commitButton).toBeEnabled();
  await commitButton.click();
  await expect(page.getByRole("button", { name: "已提交" })).toBeVisible();
  await expect(page.getByText("不可修改")).toBeVisible();
  await page.getByRole("button", { name: "下一页" }).click();
  await expect(page.getByText("第 51–51 行，共 51 行")).toBeVisible();
  await expect(page.getByRole("cell", { name: "51", exact: true })).toBeVisible();
});

test("export filters saved journeys and downloads both GPX modes", async ({ page }) => {
  let previewBody: Record<string, unknown> | undefined;
  await page.route("**/api/v1/journeys?**", (route) =>
    route.fulfill({
      contentType: "application/json",
      json: { items: [journey], total: 1 },
    }),
  );
  await page.route("**/api/v1/exports/preview", async (route) => {
    previewBody = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({
      contentType: "application/json",
      json: {
        preview_token: "preview-token",
        journey_count: 1,
        edge_count: 1,
        unique_edge_count: 1,
        distance_m: 18_342.7,
        track_count: 1,
        segment_count: 1,
        dataset_version_ids: [1],
        rail_dataset_version_ids: [],
        rail_graph_versions: [],
        blocking_errors: [],
        warnings: [],
      },
    });
  });
  await page.route("**/api/v1/exports/gpx", (route) =>
    route.fulfill({
      body: '<?xml version="1.0"?><gpx version="1.1" creator="Transit2Fog"/>',
      contentType: "application/gpx+xml",
      headers: { "Content-Disposition": 'attachment; filename="transit2fog.gpx"' },
    }),
  );

  await page.goto("/exports");
  await expect(page.getByText("18.3 km")).toBeVisible();
  await page.getByLabel("仅勾选的行程").check();
  await page.getByLabel("城市").selectOption("1");
  await page.getByRole("checkbox", { name: /J-20260820-001/ }).check();
  await expect.poll(() => previewBody).toMatchObject({ city_id: 1, journey_ids: [7] });
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "生成 GPX" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("transit2fog.gpx");

  await page.getByLabel("行程模式（保留每次行程）").check();
  await expect.poll(() => previewBody).toMatchObject({ mode: "journeys" });
  const journeyDownloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "生成 GPX" }).click();
  const journeyDownload = await journeyDownloadPromise;
  expect(journeyDownload.suggestedFilename()).toBe("transit2fog.gpx");
});

test("journey pagination and server search reach records beyond the first hundred", async ({ page }) => {
  const records = Array.from({ length: 125 }, (_, index) => ({ ...journey, id: index + 1, journey_code: `trip-${index + 1}`, note: index === 124 ? "旧记录专用备注" : null }));
  let detailRequests = 0;
  await page.route("**/api/v1/journeys**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/journeys") {
      const query = url.searchParams.get("q") ?? "";
      const matches = records.filter((item) => !query || item.note?.includes(query));
      const offset = Number(url.searchParams.get("offset") ?? 0);
      const limit = Number(url.searchParams.get("limit") ?? 50);
      await route.fulfill({ json: { items: matches.slice(offset, offset + limit), total: matches.length } });
    } else if (url.pathname === "/api/v1/journeys/125") {
      detailRequests += 1;
      await route.fulfill({ json: records[124] });
    } else await route.fallback();
  });
  await page.goto("/journeys");
  await expect(page.getByText("第 1–50 条，共 125 条")).toBeVisible();
  expect(detailRequests).toBe(0);
  await page.getByRole("button", { name: "下一页" }).click();
  await expect(page.getByText("第 51–100 条，共 125 条")).toBeVisible();
  await page.getByRole("button", { name: "下一页" }).click();
  await expect(page.getByText("第 101–125 条，共 125 条")).toBeVisible();
  await page.getByPlaceholder("按城市、线路、站点、编号或备注筛选").fill("旧记录专用备注");
  await expect(page.locator(".journey-card")).toHaveCount(1);
  await expect(page.getByText("第 1–1 条，共 1 条")).toBeVisible();
  await page.getByText("查看详情").click();
  await expect(page.getByText(/数据版本 1 · 1 个区间/)).toBeVisible();
  expect(detailRequests).toBe(1);
});

test("export selection retains IDs across pages and loads complete filter facets", async ({ page }) => {
  const records = Array.from({ length: 125 }, (_, index) => ({ ...journey, id: index + 1, journey_code: `export-${index + 1}` }));
  let selection: number[] = [];
  await page.route("**/api/v1/journeys/filters", (route) => route.fulfill({ json: {
    cities: [{ id: 1, name: "上海" }, { id: 99, name: "历史城市" }],
    lines: [{ id: 2, name: "2号线", city_id: 1 }, { id: 99, name: "历史线路", city_id: 99 }],
  }}));
  await page.route("**/api/v1/journeys?**", (route) => {
    const url = new URL(route.request().url());
    const offset = Number(url.searchParams.get("offset") ?? 0);
    return route.fulfill({ json: { items: records.slice(offset, offset + 50), total: records.length } });
  });
  await page.route("**/api/v1/exports/preview", (route) => {
    const body = route.request().postDataJSON() as { journey_ids: number[] };
    selection = body.journey_ids;
    return route.fulfill({ json: { preview_token: "test-token", journey_count: selection.length || 125, edge_count: 2, unique_edge_count: 2, distance_m: 1000, track_count: 1, segment_count: 1, dataset_version_ids: [1], rail_dataset_version_ids: [], rail_graph_versions: [], warnings: [], blocking_errors: [] } });
  });
  await page.goto("/exports");
  await expect(page.getByLabel("城市").locator("option")).toHaveCount(3);
  await page.getByLabel("仅勾选的行程").check();
  await page.getByRole("checkbox", { name: /export-1$/, exact: false }).check();
  await page.getByRole("button", { name: "下一页" }).click();
  await expect(page.getByText("第 51–100 条，共 125 条")).toBeVisible();
  await page.getByRole("button", { name: "下一页" }).click();
  await page.getByRole("checkbox", { name: /export-125$/ }).check();
  await expect.poll(() => selection).toEqual([1, 125]);
  await expect(page.getByText("已选择 2 条行程（跨页保留）")).toBeVisible();
  await page.getByRole("button", { name: "上一页" }).click();
  await expect(page.getByText("第 51–100 条，共 125 条")).toBeVisible();
  await page.getByRole("button", { name: "上一页" }).click();
  await expect(page.getByRole("checkbox", { name: /export-1$/ })).toBeChecked();
});

test("CSV task survives refresh and can pause and resume", async ({ page }) => {
  let status = "parsing";
  let processed = 1;
  const batch = () => ({ id: 91, filename: "resume.csv", encoding: "utf-8", total_rows: 3, processed_rows: processed, resolved_rows: processed, review_rows: 0, failed_rows: 0, status, error_message: null, created_at: "2026-09-28T00:00:00Z", committed_at: null });
  await page.route("**/api/v1/import-batches/91**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/rows")) return route.fulfill({ json: { items: [], total: 0 } });
    if (url.pathname.endsWith("/cancel")) status = "cancelled";
    if (url.pathname.endsWith("/resume")) { status = "ready_for_review"; processed = 3; }
    return route.fulfill({ json: batch() });
  });
  await page.goto("/imports/csv?batch=91");
  await expect(page.getByRole("progressbar", { name: "CSV 解析进度" })).toHaveAttribute("value", "1");
  await expect(page.getByRole("button", { name: "提交全部已审核行" })).toBeDisabled();
  await page.getByRole("button", { name: "暂停解析" }).click();
  await page.reload();
  await expect(page.getByRole("button", { name: "继续解析" })).toBeVisible();
  await expect(page).toHaveURL(/batch=91/);
  await page.getByRole("button", { name: "继续解析" }).click();
  await expect(page.getByRole("button", { name: "提交全部已审核行" })).toBeEnabled();
  await expect(page.getByText("3 已解析", { exact: true })).toBeVisible();
});
