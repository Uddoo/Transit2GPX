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
  { id: 2, city_id: 1, name_cn: "2号线", name_en: "Line 2", display_color: "#079aa4" },
];
const STATIONS = [
  { id: 101, city_id: 1, name_cn: "虹桥火车站", name_en: "Hongqiao Railway Station", lon: 121.312, lat: 31.194 },
  { id: 132, city_id: 1, name_cn: "人民广场", name_en: "People's Square", lon: 121.475, lat: 31.231 },
];
const PATH_PREVIEW = {
  status: "resolved",
  candidates: [
    {
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
const EXPORT_PREVIEW = {
  preview_token: `sha256:${"a".repeat(64)}`,
  journey_count: 1,
  edge_count: 1,
  unique_edge_count: 1,
  distance_m: 18342.7,
  track_count: 1,
  segment_count: 1,
  dataset_version_ids: [1],
  blocking_errors: [],
  warnings: [],
};

function jsonResponse(body: unknown) {
  return { ok: true, status: 200, json: () => Promise.resolve(body) };
}

describe("Metro2Fog app shell", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url =
          input instanceof Request
            ? input.url
            : input instanceof URL
              ? input.href
              : input;
        if (url.includes("/api/v1/config/public")) {
          return Promise.resolve(jsonResponse(PUBLIC_CONFIG));
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
          return Promise.resolve(jsonResponse(PATH_PREVIEW));
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
        if (url.endsWith("/api/v1/journeys")) {
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

    expect(screen.getByRole("heading", { name: "添加一段真实乘坐记录" })).toBeInTheDocument();
    const previewButton = screen.getByRole("button", { name: "预览路径" });
    await waitFor(() => expect(previewButton).toBeEnabled());
    await user.click(previewButton);

    expect(screen.getByRole("heading", { name: "候选路径" })).toHaveFocus();
    expect(screen.getByText("2号线 · 虹桥火车站 → 人民广场")).toBeInTheDocument();
    expect(screen.getByText("候选路径", { selector: ".map-candidate-legend" })).toHaveAttribute(
      "data-route-color",
      "#6d28d9",
    );

    await user.click(screen.getByRole("button", { name: "保存行程" }));
    expect(screen.getByRole("button", { name: "已保存" })).toBeInTheDocument();
    expect(screen.getByText("行程已保存。")).toBeInTheDocument();
  });

  it("searches and selects both endpoint stations with the keyboard", async () => {
    const user = userEvent.setup();
    renderApp(<App />);

    const startStation = screen.getByRole("combobox", { name: "起点站" });
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

    const line = screen.getByRole("combobox", { name: "线路" });
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
    const createObjectUrl = vi.fn(() => "blob:metro2fog-direct");
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

    const previewButton = screen.getByRole("button", { name: "预览路径" });
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

  it("navigates to the CSV upload and review flow", async () => {
    const user = userEvent.setup();
    renderApp(<App />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "预览路径" })).toBeEnabled(),
    );
    await user.click(screen.getAllByRole("link", { name: "CSV 导入" })[0]);

    expect(screen.getByRole("heading", { name: "CSV 导入" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "选择 CSV 文件" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下载模板" })).toBeInTheDocument();
    expect(screen.getByText("选择一个 CSV 文件")).toBeInTheDocument();
  });
});
