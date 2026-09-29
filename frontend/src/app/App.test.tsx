import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { renderApp } from "../test/renderApp";

const DATA_STATUS = {
  status: "ready",
  dataset: "CPTOND-2025",
  captured_at: "2025-06",
  license: "CC BY 4.0",
  cities: 46,
  imported_at: "2026-08-20T00:00:00Z",
  quality_status: "ready",
};

const PUBLIC_CONFIG = {
  map: {
    tiles_enabled: true,
    tile_url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    tile_attribution: "© OpenStreetMap contributors",
    max_zoom: 19,
    external_tiles: true,
  },
};

const CITY_MAP = {
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
          coordinates: [
            [121.312, 31.194],
            [121.381, 31.209],
            [121.475, 31.231],
          ],
        },
        properties: { name_cn: "2号线", display_color: "#079aa4" },
      },
    ],
  },
  stations: { type: "FeatureCollection", features: [] },
};

const CITIES = [
  { id: 1, name_cn: "上海", name_en: "Shanghai", center: [121.47, 31.23], bbox: CITY_MAP.bbox },
];
const LINES = [
  { id: 10, city_id: 1, name_cn: "10号线", name_en: "Line 10", display_color: "#079aa4" },
  { id: 2, city_id: 1, name_cn: "2号线", name_en: "Line 2", display_color: "#079aa4" },
  { id: 6, city_id: 1, name_cn: "6号线", name_en: "Line 6", display_color: "#079aa4" },
];
const STATIONS = [
  { id: 101, city_id: 1, name_cn: "虹桥火车站", name_en: "Hongqiao Railway Station", lon: 121.312, lat: 31.194 },
  { id: 132, city_id: 1, name_cn: "人民广场", name_en: "People's Square", lon: 121.475, lat: 31.231 },
];
const PATH_PREVIEW = {
  status: "resolved",
  candidates: [
    {
      mode: "metro",
      candidate_id: "cand_test",
      digest: "sha256:test",
      dataset_version_id: 1,
      route_variant_id: 18,
      line_name: "2号线",
      direction_name: "正向",
      distance_m: 18342.7,
      station_count: 13,
      station_ids: [101, 132],
      edge_ids: [501],
      reversed_edges: [false],
      geometry: CITY_MAP.lines.features[0].geometry,
      warnings: [],
    },
  ],
};
const RAIL_STATUS = {
  status: "ready",
  enabled: true,
  sidecar_available: true,
  rail_dataset_version_id: 9,
  dataset_status: "ready",
  station_count: 2,
  graph_version: "yangtze-r0.1",
  profile_version: "2026-08-21-r0.1",
  pbf_checksum: "test",
  source_url: "https://download.geofabrik.de/asia/china.html",
  source_timestamp: "2026-08-20",
  extract_region: "yangtze",
  license: "ODbL-1.0",
  profiles: ["china_high_speed", "china_emu", "china_conventional"],
  bbox: [118, 29, 122, 33],
  error_code: null,
  error_message: null,
};
const RAIL_STATIONS = [
  {
    id: 801,
    rail_dataset_version_id: 9,
    osm_type: "node",
    osm_id: 801,
    name_cn: "上海虹桥",
    name_en: "Shanghai Hongqiao",
    station_code: "AOH",
    city_name: "上海",
    province_name: "上海",
    lon: 121.327,
    lat: 31.2,
    match_score: 100,
    match_method: "name",
  },
  {
    id: 802,
    rail_dataset_version_id: 9,
    osm_type: "node",
    osm_id: 802,
    name_cn: "杭州东",
    name_en: "Hangzhoudong",
    station_code: "HGH",
    city_name: "杭州",
    province_name: "浙江",
    lon: 120.212,
    lat: 30.29,
    match_score: 100,
    match_method: "name",
  },
];
const RAIL_PATH_PREVIEW = {
  status: "needs_review",
  candidates: [
    {
      mode: "rail",
      candidate_id: "rail_cand_test",
      digest: `sha256:${"b".repeat(64)}`,
      rail_dataset_version_id: 9,
      graph_version: "yangtze-r0.1",
      profile_version: "2026-08-21-r0.1",
      scoring_version: "2026-08-21-r0.2",
      routing_profile: "china_high_speed",
      distance_m: 159000,
      duration_ms: 3600000,
      station_count: 2,
      station_ids: [801, 802],
      geometry: {
        type: "LineString",
        coordinates: [
          [121.327, 31.2],
          [120.212, 30.29],
        ],
      },
      way_ranges: [{ start_index: 0, end_index: 1, osm_way_id: 9901 }],
      score: 0.95,
      score_details: [],
      warnings: [],
      can_commit: true,
    },
  ],
};
const SAVED_JOURNEY = {
  id: 7,
  journey_code: "trip-test",
  traveled_at: null,
  source_type: "manual",
  note: null,
  created_at: "2026-08-21T00:00:00Z",
  updated_at: "2026-08-21T00:00:00Z",
  distance_m: 18342.7,
  legs: [],
};
const SAVED_RAIL_JOURNEY = {
  ...SAVED_JOURNEY,
  id: 8,
  journey_code: "rail-trip-test",
  traveled_at: "2026-08-20",
  distance_m: 159000,
  legs: [
    {
      id: 81,
      leg_no: 1,
      transport_mode: "rail",
      dataset_version_id: null,
      rail_dataset_version_id: 9,
      graph_version: "yangtze-r0.1",
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
      candidate_digest: RAIL_PATH_PREVIEW.candidates[0].digest,
      edge_ids: [91],
      reversed_edges: [false],
      distance_m: 159000,
    },
  ],
};
const RAIL_RECOMPUTE_PREVIEW = {
  journey_id: 8,
  target_graph_version: "china-r1.0",
  target_profile_version: "2026-08-21-r0.1",
  legs: [
    {
      leg_no: 1,
      source_graph_version: "yangtze-r0.1",
      target_graph_version: "china-r1.0",
      station_names: ["上海虹桥", "杭州东"],
      status: "needs_review",
      candidates: [
        {
          ...RAIL_PATH_PREVIEW.candidates[0],
          rail_dataset_version_id: 10,
          graph_version: "china-r1.0",
          candidate_id: "rail_cand_recompute",
          digest: `sha256:${"c".repeat(64)}`,
          score: 0.97,
        },
      ],
    },
  ],
};
const EXPORT_PREVIEW = {
  preview_token: `sha256:${"a".repeat(64)}`,
  journey_count: 1,
  edge_count: 1,
  unique_edge_count: 1,
  distance_m: 18342.7,
  track_count: 1,
  segment_count: 1,
  dataset_version_ids: [1],
  rail_dataset_version_ids: [],
  rail_graph_versions: [],
  blocking_errors: [],
  warnings: [],
};

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Transit2Fog app shell", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url =
          input instanceof Request
            ? input.url
            : input instanceof URL
              ? input.href
              : input;
        if (url.includes("/api/v1/config/public")) {
          return Promise.resolve(jsonResponse(PUBLIC_CONFIG));
        }
        if (url.includes("/api/v1/rail/data/status")) {
          return Promise.resolve(jsonResponse(RAIL_STATUS));
        }
        if (url.includes("/api/v1/rail/stations/search")) {
          const query = new URL(url, "http://localhost").searchParams.get("q");
          return Promise.resolve(
            jsonResponse(
              RAIL_STATIONS.filter((station) => station.name_cn.includes(query ?? "")),
            ),
          );
        }
        if (url.includes("/api/v1/cities/1/map")) {
          return Promise.resolve(jsonResponse(CITY_MAP));
        }
        if (url.endsWith("/api/v1/cities")) {
          return Promise.resolve(jsonResponse(CITIES));
        }
        if (url.includes("/api/v1/cities/1/lines")) {
          return Promise.resolve(jsonResponse(LINES));
        }
        if (url.includes("/api/v1/lines/2/stations")) {
          return Promise.resolve(jsonResponse(STATIONS));
        }
        if (url.includes("/api/v1/cities/1/stations")) {
          return Promise.resolve(jsonResponse(STATIONS));
        }
        if (url.includes("/api/v1/stations/search")) {
          const query = new URL(url, "http://localhost").searchParams.get("q");
          return Promise.resolve(
            jsonResponse(query === "renmin" ? [STATIONS[1]] : []),
          );
        }
        if (url.includes("/api/v1/paths/preview")) {
          const body = typeof init?.body === "string" ? JSON.parse(init.body) as { mode?: string } : {};
          return Promise.resolve(
            jsonResponse(body.mode === "rail" ? RAIL_PATH_PREVIEW : PATH_PREVIEW),
          );
        }
        if (url.includes("/api/v1/exports/preview")) {
          return Promise.resolve(jsonResponse(EXPORT_PREVIEW));
        }
        if (url.includes("/api/v1/exports/gpx")) {
          return Promise.resolve({
            ok: true,
            status: 200,
            headers: new Headers({
              "Content-Disposition": 'attachment; filename="direct.gpx"',
            }),
            blob: () => Promise.resolve(new Blob(["<gpx />"])),
          });
        }
        if (new URL(url, "http://localhost").pathname === "/api/v1/journeys") {
          return Promise.resolve(jsonResponse(SAVED_JOURNEY));
        }
        return Promise.resolve(jsonResponse(DATA_STATUS));
      }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("previews and saves a selected journey candidate", async () => {
    const user = userEvent.setup();
    renderApp(<App />);
    await screen.findByRole("button", { name: "预览路径" });

    const homeLinks = screen.getAllByRole("link", { name: "Transit2Fog 首页" });
    expect(homeLinks).toHaveLength(2);
    expect(homeLinks[0]).toHaveTextContent("Transit2Fog");
    expect(
      screen.getByText("记录真实地铁与铁路行程，导出 Fog of World 可用的 GPX"),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "添加一段真实乘坐记录" })).toBeInTheDocument();
    const previewButton = screen.getByRole("button", { name: "预览路径" });
    expect(previewButton).toBeDisabled();
    await waitFor(() => expect(screen.getByRole("button", { name: "选择首末站" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "选择首末站" }));
    await waitFor(() => expect(previewButton).toBeEnabled());
    await user.click(previewButton);

    expect(screen.getByRole("heading", { name: "候选路径" })).toHaveFocus();
    expect(screen.getByText("2号线 · 虹桥火车站 → 人民广场")).toBeInTheDocument();
    expect(screen.getByText("候选路径", { selector: ".map-candidate-legend" })).toHaveAttribute(
      "data-route-color",
      "#079aa4",
    );

    await user.click(screen.getByRole("button", { name: "保存行程" }));
    expect(screen.getByRole("button", { name: "已保存" })).toBeInTheDocument();
    expect(screen.getByText("行程已保存。")).toBeInTheDocument();
  });

  it("sorts metro lines by their natural Chinese line names", async () => {
    renderApp(<App />);
    await screen.findByRole("button", { name: "预览路径" });

    const line = await screen.findByRole("combobox", { name: "线路" });
    await waitFor(() => expect(line).toBeEnabled());

    expect(
      within(line)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual([
      "选择线路",
      "自动规划换乘（需确认）",
      "2号线",
      "6号线",
      "10号线",
    ]);
    expect(line).toHaveValue("2");
  });

  it("searches and selects both endpoint stations with the keyboard", async () => {
    const user = userEvent.setup();
    renderApp(<App />);
    await screen.findByRole("button", { name: "预览路径" });

    const startStation = await screen.findByRole("combobox", { name: "起点站" });
    const endStation = screen.getByRole("combobox", { name: "终点站" });
    await waitFor(() => expect(startStation).toBeEnabled());

    await user.click(startStation);
    await user.type(startStation, "renmin");
    await waitFor(() =>
      expect(
        within(screen.getByRole("listbox")).getByRole("option", {
          name: /人民广场/,
        }),
      ).toBeInTheDocument(),
    );
    await user.keyboard("{Enter}");
    expect(startStation).toHaveValue("人民广场");

    await user.click(endStation);
    await user.type(endStation, "虹桥");
    expect(
      within(screen.getByRole("listbox")).getByRole("option", {
        name: /虹桥火车站/,
      }),
    ).toBeInTheDocument();
    await user.keyboard("{Enter}");
    expect(endStation).toHaveValue("虹桥火车站");
    expect(screen.getByRole("button", { name: "预览路径" })).toBeEnabled();
  });

  it("searches and clears a via station while automatic transfers are enabled", async () => {
    const user = userEvent.setup();
    renderApp(<App />);
    await screen.findByRole("button", { name: "预览路径" });

    const line = await screen.findByRole("combobox", { name: "线路" });
    await waitFor(() => expect(line).toBeEnabled());
    await user.selectOptions(line, "auto");

    const viaStation = screen.getByRole("combobox", {
      name: "途经站（可选）",
    });
    await waitFor(() => expect(viaStation).toBeEnabled());
    expect(viaStation).toHaveValue("不指定");

    await user.click(viaStation);
    await user.type(viaStation, "renmin");
    await waitFor(() =>
      expect(
        within(screen.getByRole("listbox")).getByRole("option", {
          name: /人民广场/,
        }),
      ).toBeInTheDocument(),
    );
    await user.keyboard("{Enter}");
    expect(viaStation).toHaveValue("人民广场");

    await user.click(viaStation);
    await user.click(
      within(screen.getByRole("listbox")).getByRole("option", {
        name: /不指定/,
      }),
    );
    expect(viaStation).toHaveValue("不指定");
  });

  it("saves and directly exports the selected candidate as GPX", async () => {
    const user = userEvent.setup();
    const createObjectUrl = vi.fn(() => "blob:transit2fog-direct");
    const revokeObjectUrl = vi.fn();
    const BrowserUrl = class extends URL {};
    Object.defineProperties(BrowserUrl, {
      createObjectURL: { value: createObjectUrl },
      revokeObjectURL: { value: revokeObjectUrl },
    });
    vi.stubGlobal("URL", BrowserUrl);
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    renderApp(<App />);
    await screen.findByRole("button", { name: "预览路径" });

    const previewButton = await screen.findByRole("button", { name: "预览路径" });
    expect(previewButton).toBeDisabled();
    await waitFor(() => expect(screen.getByRole("button", { name: "选择首末站" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "选择首末站" }));
    await waitFor(() => expect(previewButton).toBeEnabled());
    await user.click(previewButton);
    await user.click(screen.getByRole("button", { name: "导出 GPX" }));

    await waitFor(() => expect(createObjectUrl).toHaveBeenCalledOnce());
    expect(anchorClick).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "已保存" })).toBeInTheDocument();
    const exportPreviewCall = vi
      .mocked(fetch)
      .mock.calls.find(
        ([input]) =>
          typeof input === "string" && input.includes("/api/v1/exports/preview"),
      );
    const exportPreviewBody = exportPreviewCall?.[1]?.body;
    expect(typeof exportPreviewBody).toBe("string");
    if (typeof exportPreviewBody !== "string") throw new Error("Missing export body");
    expect(JSON.parse(exportPreviewBody)).toMatchObject({
      mode: "journeys",
      journey_ids: [7],
    });
  });

  it("searches railway stations, previews a candidate, and saves the confirmed snapshot", async () => {
    const user = userEvent.setup();
    renderApp(<App />);
    await screen.findByRole("button", { name: "预览路径" });

    await user.click(await screen.findByRole("tab", { name: "铁路 / 高铁" }));
    expect(
      await screen.findByRole("heading", { name: "添加一段真实铁路乘坐记录" }),
    ).toBeInTheDocument();

    const date = screen.getByLabelText("乘坐日期（必填）");
    const start = screen.getByRole("combobox", { name: "上车站" });
    const end = screen.getByRole("combobox", { name: "下车站" });
    await waitFor(() => expect(start).toBeEnabled());
    await user.type(date, "2026-08-20");
    await user.click(start);
    await user.type(start, "上海虹桥");
    await waitFor(() =>
      expect(within(screen.getByRole("listbox")).getByRole("option", { name: /上海虹桥/ })).toBeInTheDocument(),
    );
    await user.keyboard("{Enter}");
    await user.click(end);
    await user.type(end, "杭州东");
    await waitFor(() =>
      expect(within(screen.getByRole("listbox")).getByRole("option", { name: /杭州东/ })).toBeInTheDocument(),
    );
    await user.keyboard("{Enter}");

    await user.click(screen.getByRole("button", { name: "预览铁路路径" }));
    expect(await screen.findByRole("heading", { name: "铁路候选" })).toHaveFocus();
    expect(screen.getByRole("heading", { name: "铁路候选" }).closest(".candidate-rail")).toHaveClass(
      "candidate-rail--rail",
    );
    expect(screen.getByRole("button", { name: "保存并导出" })).toHaveClass("button--primary");
    expect(screen.getByRole("button", { name: "确认并保存" })).toHaveClass("button--secondary");
    expect(screen.getByText("159.0 km")).toBeInTheDocument();
    expect(screen.getByText("95%")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "确认并保存" }));
    expect(await screen.findByRole("button", { name: "已保存" })).toBeDisabled();

    const createCall = vi.mocked(fetch).mock.calls.find(([input, init]) => {
      const url = input instanceof Request
        ? input.url
        : input instanceof URL
          ? input.href
          : input;
      return new URL(url, "http://localhost").pathname === "/api/v1/journeys" && init?.method === "POST";
    });
    const createBody = createCall?.[1]?.body;
    expect(typeof createBody).toBe("string");
    if (typeof createBody !== "string") throw new Error("Missing rail journey body");
    expect(JSON.parse(createBody)).toMatchObject({
      traveled_at: "2026-08-20",
      legs: [{ mode: "rail", start_station_id: 801, end_station_id: 802 }],
    });
  });

  it("keeps railway facts interactive and explains when railway data is disabled", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url =
        input instanceof Request
          ? input.url
          : input instanceof URL
            ? input.href
            : input;
      if (url.includes("/api/v1/config/public")) {
        return Promise.resolve(jsonResponse(PUBLIC_CONFIG));
      }
      if (url.includes("/api/v1/rail/data/status")) {
        return Promise.resolve(
          jsonResponse({
            ...RAIL_STATUS,
            status: "disabled",
            enabled: false,
            sidecar_available: false,
            rail_dataset_version_id: null,
            dataset_status: null,
            station_count: 0,
            graph_version: null,
            profile_version: null,
            profiles: [],
          }),
        );
      }
      if (url.includes("/api/v1/cities/1/map")) {
        return Promise.resolve(jsonResponse(CITY_MAP));
      }
      if (url.endsWith("/api/v1/cities")) {
        return Promise.resolve(jsonResponse(CITIES));
      }
      if (url.includes("/api/v1/cities/1/lines")) {
        return Promise.resolve(jsonResponse(LINES));
      }
      if (url.includes("/api/v1/lines/2/stations")) {
        return Promise.resolve(jsonResponse(STATIONS));
      }
      return Promise.resolve(jsonResponse(DATA_STATUS));
    });
    renderApp(<App />);
    await screen.findByRole("button", { name: "预览路径" });

    await user.click(await screen.findByRole("tab", { name: "铁路 / 高铁" }));
    expect(await screen.findByText("铁路功能暂不可用")).toBeInTheDocument();

    const date = screen.getByLabelText("乘坐日期（必填）");
    const trainNo = screen.getByLabelText("车次（建议）");
    const trainType = screen.getByLabelText("车型");
    const start = screen.getByRole("combobox", { name: "上车站" });
    expect(date).toBeEnabled();
    expect(trainNo).toBeEnabled();
    expect(trainType).toBeEnabled();
    expect(start).toBeEnabled();

    await user.type(date, "2026-08-21");
    await user.type(trainNo, "G1");
    await user.selectOptions(trainType, "D");
    expect(date).toHaveValue("2026-08-21");
    expect(trainNo).toHaveValue("G1");
    expect(trainType).toHaveValue("D");

    await user.click(start);
    await user.type(start, "北京南");
    expect(
      screen.getByText(/当前本地服务未启用铁路功能/, {
        selector: ".station-combobox__status",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "铁路数据就绪后可预览" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "查看铁路设置" })).toHaveAttribute(
      "href",
      "/settings/data",
    );
  });

  it("navigates to the CSV upload and review flow", async () => {
    const user = userEvent.setup();
    renderApp(<App />);
    await screen.findByRole("button", { name: "预览路径" });

    await waitFor(() => expect(screen.getByRole("combobox", { name: "城市" })).toBeEnabled());
    await user.click(screen.getAllByRole("link", { name: "CSV 导入" })[0]);

    expect(await screen.findByRole("heading", { name: "CSV 导入" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "选择 CSV 文件" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载模板" })).toBeInTheDocument();
    expect(screen.getByText("选择一个 CSV 文件")).toBeInTheDocument();
  });

  it("pauses and resumes a CSV batch opened from its persisted URL", async () => {
    const user = userEvent.setup();
    let status = "parsing";
    let processed = 1;
    const fallback = vi.mocked(fetch).getMockImplementation();
    if (!fallback) throw new Error("Missing fetch fixture");
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
      const pathname = new URL(url, "http://localhost").pathname;
      if (pathname.startsWith("/api/v1/import-batches/91")) {
        if (pathname.endsWith("/rows")) return Promise.resolve(jsonResponse({ items: [], total: 0 }));
        if (pathname.endsWith("/cancel")) status = "cancelled";
        if (pathname.endsWith("/resume")) { status = "ready_for_review"; processed = 3; }
        return Promise.resolve(jsonResponse({ id: 91, filename: "resume.csv", encoding: "utf-8", total_rows: 3, processed_rows: processed, resolved_rows: processed, review_rows: 0, failed_rows: 0, status, error_message: null, created_at: "2026-09-28T00:00:00Z", committed_at: null }));
      }
      return fallback(input, init);
    });
    renderApp(<App />, "/imports/csv?batch=91");
    expect(await screen.findByRole("progressbar", { name: "CSV 解析进度" })).toHaveAttribute("value", "1");
    expect(screen.getByRole("button", { name: "提交全部已审核行" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "暂停解析" }));
    await user.click(await screen.findByRole("button", { name: "继续解析" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "提交全部已审核行" })).toBeEnabled());
    expect(screen.getByText("3 已解析")).toBeInTheDocument();
  });

  it("loads journey pages from the API", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url =
        input instanceof Request
          ? input.url
          : input instanceof URL
            ? input.href
            : input;
      if (url.includes("/api/v1/config/public")) {
        return Promise.resolve(jsonResponse(PUBLIC_CONFIG));
      }
      if (url.includes("/api/v1/rail/data/status")) {
        return Promise.resolve(jsonResponse(RAIL_STATUS));
      }
      if (url.includes("/api/v1/journeys?")) {
        const offset = Number(new URL(url, "http://localhost").searchParams.get("offset"));
        const secondPage = offset === 50;
        return Promise.resolve(
          jsonResponse({
            items: Array.from({ length: secondPage ? 1 : 50 }, (_, index) => ({
              ...SAVED_JOURNEY,
              id: offset + index + 1,
              journey_code: `page-trip-${String(offset + index + 1).padStart(2, "0")}`,
            })),
            total: 51,
            limit: 50,
            offset,
            has_more: !secondPage,
          }),
        );
      }
      return Promise.resolve(jsonResponse(DATA_STATUS));
    });
    renderApp(<App />, "/journeys");

    expect(await screen.findByText("page-trip-01")).toBeInTheDocument();
    expect(screen.getByText("第 1–50 条，共 51 条")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(await screen.findByText("page-trip-51")).toBeInTheDocument();
    expect(screen.getByText("第 51–51 条，共 51 条")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
  });

  it("previews and confirms an immutable railway journey recompute", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url =
          input instanceof Request
            ? input.url
            : input instanceof URL
              ? input.href
              : input;
        if (url.includes("/api/v1/config/public")) {
          return Promise.resolve(jsonResponse(PUBLIC_CONFIG));
        }
        if (url.includes("/api/v1/rail/data/status")) {
          return Promise.resolve(jsonResponse(RAIL_STATUS));
        }
        if (url.endsWith("/rail-recompute/preview")) {
          return Promise.resolve(jsonResponse(RAIL_RECOMPUTE_PREVIEW));
        }
        if (url.endsWith("/rail-recompute") && init?.method === "POST") {
          return Promise.resolve(
            jsonResponse({
              ...SAVED_RAIL_JOURNEY,
              id: 9,
              journey_code: "rail-trip-recomputed",
              legs: [
                {
                  ...SAVED_RAIL_JOURNEY.legs[0],
                  graph_version: "china-r1.0",
                },
              ],
            }),
          );
        }
        if (new URL(url, "http://localhost").pathname === "/api/v1/journeys") {
          return Promise.resolve(
            jsonResponse({
              items: [SAVED_RAIL_JOURNEY],
              total: 1,
              limit: 20,
              offset: 0,
              has_more: false,
            }),
          );
        }
        return Promise.resolve(jsonResponse(DATA_STATUS));
      },
    );
    renderApp(<App />, "/journeys");

    await user.click(await screen.findByRole("button", { name: "重算铁路" }));
    expect(
      await screen.findByRole("heading", { name: "按新铁路图重算" }),
    ).toBeInTheDocument();
    expect(screen.getByText("yangtze-r0.1 → china-r1.0")).toBeInTheDocument();
    expect(screen.getByText(/评分 97%/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "确认并创建新行程" }));

    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: "按新铁路图重算" }),
      ).not.toBeInTheDocument(),
    );
    const confirmCall = vi.mocked(fetch).mock.calls.find(([input, init]) => {
      const url =
        input instanceof Request
          ? input.url
          : input instanceof URL
            ? input.href
            : input;
      return url.endsWith("/rail-recompute") && init?.method === "POST";
    });
    const body = confirmCall?.[1]?.body;
    expect(typeof body).toBe("string");
    if (typeof body !== "string") throw new Error("Missing recompute body");
    expect(JSON.parse(body)).toMatchObject({
      target_graph_version: "china-r1.0",
      selections: [
        {
          leg_no: 1,
          candidate_id: "rail_cand_recompute",
          candidate_digest: `sha256:${"c".repeat(64)}`,
        },
      ],
    });
  });
});
