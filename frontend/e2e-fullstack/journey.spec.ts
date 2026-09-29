import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";

test("creates, persists, and exports a metro journey through the real stack", async ({
  page,
  request,
}) => {
  const health = await request.get("/healthz");
  expect(health.ok()).toBeTruthy();
  await expect(health.json()).resolves.toMatchObject({
    status: "ok",
    version: "1.0.0",
    database: "ok",
  });

  const status = await request.get("/api/v1/data/status");
  expect(status.ok()).toBeTruthy();
  await expect(status.json()).resolves.toMatchObject({
    status: "ready",
    ready_available: true,
    cities: 1,
  });

  await page.goto("/journeys/new");
  await expect(
    page.getByRole("heading", { name: "添加一段真实乘坐记录" }),
  ).toBeVisible();
  await expect(page.getByRole("combobox", { name: "城市" })).toHaveValue("1");
  await expect(page.getByRole("combobox", { name: "线路" })).toHaveValue("1");
  await expect(page.getByRole("combobox", { name: "起点站" })).toHaveValue("");
  await expect(page.getByRole("combobox", { name: "终点站" })).toHaveValue("");
  await expect(page.getByRole("button", { name: "预览路径" })).toBeDisabled();
  await page.getByRole("button", { name: "选择首末站" }).click();
  await expect(page.getByRole("combobox", { name: "起点站" })).toHaveValue("甲站");
  await expect(page.getByRole("combobox", { name: "终点站" })).toHaveValue("丙站");
  await expect(
    page.getByRole("region", { name: "真实地理底图与已导入地铁线路" }),
  ).toBeVisible();

  await page.getByLabel("乘坐日期（可选）").fill("2026-08-31");
  await page.getByLabel("备注（可选）").fill("真实全栈验收");
  await page.getByRole("button", { name: "预览路径" }).click();
  await expect(page.getByRole("heading", { name: "候选路径" })).toBeVisible();
  await expect(page.getByText("测试线 · 甲站 → 丙站")).toBeVisible();
  await page.getByRole("button", { name: "保存行程" }).click();
  await expect(page.getByRole("button", { name: "已保存" })).toBeVisible();

  const journeysResponse = await request.get("/api/v1/journeys");
  expect(journeysResponse.ok()).toBeTruthy();
  const journeys = (await journeysResponse.json()) as {
    total: number;
    items: { note: string | null; legs: { edge_ids: number[] }[] }[];
  };
  expect(journeys.total).toBe(1);
  expect(journeys.items[0]).toMatchObject({ note: "真实全栈验收" });
  expect(journeys.items[0].legs[0].edge_ids).toHaveLength(2);

  await page.goto("/journeys");
  await expect(page.getByText("上海 · 测试线 · 甲站 → 丙站")).toBeVisible();
  await expect(page.getByText(/真实全栈验收/)).toBeVisible();

  await page.goto("/exports");
  await expect(page.getByText("9.6 km")).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "生成 GPX" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(
    /^transit2gpx_\d{4}-\d{2}-\d{2}\.gpx$/,
  );
  const downloadPath = await download.path();
  expect(downloadPath).not.toBeNull();
  const content = await readFile(downloadPath, "utf-8");
  expect(content).toContain('<gpx xmlns="http://www.topografix.com/GPX/1/1"');
  expect(content).toContain('creator="Transit2GPX"');
  expect(content).toContain("<trkseg>");
});
