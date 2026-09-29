import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import type { CityDownloadState } from "../../api/client";
import { renderApp } from "../../test/renderApp";
import { catalogFixture, idleCityDownload } from "../../test/setupFixtures";
import { CityDataManager, InstalledCities } from "./CityDataManager";
import { CityPackImport } from "./CityPackImport";

const response = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("downloads a chosen city, retries failure and refreshes installed data once", async () => {
  let job: CityDownloadState = { ...idleCityDownload };
  let attempts = 0;
  const refresh = vi.fn(() => Promise.resolve());
  vi.stubGlobal("fetch", vi.fn((input: string, init?: RequestInit) => {
    if (input.endsWith("/catalog")) return response(catalogFixture);
    if (input.endsWith("/cities")) return response([]);
    if (input.endsWith("/download") && init?.method === "POST") {
      expect(JSON.parse(init.body as string)).toEqual({ city_code: "021" });
      attempts += 1;
      job = { ...job, city_code: "021", city_name: "上海", total_bytes: 100, status: attempts === 1 ? "failed" : "downloading", message: attempts === 1 ? "下载地址暂不可用，请重试。" : "正在下载城市数据…" };
      return response(job, 202);
    }
    if (input.endsWith("/download")) {
      if (job.status === "downloading") job = { ...job, status: "ready", downloaded_bytes: 100, dataset_id: 9, message: "上海已就绪，可以开始记录行程。" };
      return response(job);
    }
    throw new Error(`Unexpected request ${input}`);
  }));
  const user = userEvent.setup();
  renderApp(<CityDataManager refresh={refresh} />);
  await user.selectOptions(await screen.findByLabelText("选择要下载的城市"), "021");
  await user.click(screen.getByRole("button", { name: "下载并安装上海" }));
  expect(await screen.findByText("下载地址暂不可用，请重试。")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "重试城市下载" }));
  expect(await screen.findByText("上海已就绪，可以开始记录行程。", {}, { timeout: 3000 })).toBeInTheDocument();
  await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
  expect(attempts).toBe(2);
});

it("allows selecting the same local file again after an inspection failure", async () => {
  let attempts = 0;
  const entry = catalogFixture.packages[0];
  vi.stubGlobal("fetch", vi.fn(() => {
    attempts += 1;
    return attempts === 1 ? response({ error: { message: "校验失败，请重新选择" } }, 422) : response({ package_id: entry.sha256, manifest: entry.manifest, stations: 448, lines: 66, ready_variants: 66, blocked_variants: 0 });
  }));
  const user = userEvent.setup();
  renderApp(<CityPackImport refresh={() => Promise.resolve()} />);
  const file = new File(["fixture"], "shanghai.t2fcity", { type: "application/zip" });
  await user.upload(screen.getByLabelText("选择城市数据包"), file);
  await screen.findByText("校验失败，请重新选择");
  await user.upload(screen.getByLabelText("选择城市数据包"), file);
  expect(await screen.findByRole("button", { name: "安装城市数据" })).toBeEnabled();
  expect(attempts).toBe(2);
});

it("lists all installed cities and links to each city editor", async () => {
  vi.stubGlobal("fetch", vi.fn(() => response([
    { id: 1, name_cn: "上海", captured_at: "2025-06", station_count: 448, direction_count: 66 },
    { id: 2, name_cn: "杭州", captured_at: "2025-06", station_count: 325, direction_count: 44 },
  ])));
  renderApp(<InstalledCities />);
  expect(await screen.findByRole("heading", { name: "已安装城市（2）" })).toBeVisible();
  expect(screen.getAllByRole("link", { name: "记录行程" }).map((link) => link.getAttribute("href"))).toEqual(["/journeys/new?city=1", "/journeys/new?city=2"]);
});
