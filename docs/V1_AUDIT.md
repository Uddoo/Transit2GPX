# v1.0 验收审计

最后更新：2026-08-21。

## 结论

Metro2Fog v1.0 已完成验收：Science Data Bank 的 CPTOND 衍生三文件已经过真实整包导入，46 城、992 条线路全部通过质量门禁；东莞普通线路与上海环线完成了地图、方向、候选、保存及两种 GPX 抽检。合成/契约测试、双视口体验、生产启动、迁移、日志和备份恢复也有自动化或命令证据。2026-08-21，用户确认 V1.0 GPX 已在实际安装的 Fog of World 中手动导入通过，最后一个外部兼容验收项关闭。

## 功能证据

| ROADMAP 标准 | 状态 | 证据 |
|---|---|---|
| CPTOND 真实数据导入、质量报告、两城验收 | 通过 | Science Data Bank 真实包导入 46 城、992 条线路、17,731 条线路站点记录；992 ready、0 blocked。东莞与上海完成代表性抽检 |
| 手动表单与地图选站创建行程 | 通过 | Playwright 分别验证 `source_type=manual` 与 `source_type=map` 的预览、确认、保存 |
| 未指定线路换乘 | 通过 | `(station_id, line_id)` 状态图返回必须确认的候选，并按线路拆成多个 leg 事务保存 |
| CSV 上传、审核、修复与提交 | 通过 | UTF-8 限制、分页、筛选、修复、歧义选择、忽略、两段换乘归组、公式字符串安全保存、事务回滚和提交汇总均有测试 |
| 行程列表、详情、筛选、编辑、重算、删除 | 通过 | API 与响应式页面已实现；详情显示逐段版本、方向、状态和 edge 数，编辑含并发冲突保护，删除需确认 |
| journey / coverage GPX | 通过 | 两模式均有 API 与桌面/移动 E2E；coverage 连续分段、去重和断开逻辑有回归测试 |

## 正确性证据

| ROADMAP 标准 | 状态 | 证据 |
|---|---|---|
| 普通、反向、环线、支线、换乘、同名站 | 通过 | 40 个后端测试覆盖正反 edge、环线短/长弧、支线共享段歧义、换乘图、自动换乘有序途经站、线路内同名消歧、时序分段站序重建及异常几何 |
| 歧义确认、质量门禁阻止导出 | 通过 | 环线、支线、换乘返回 `needs_review`；保存后 edge 或 variant 被阻断时导出返回 `409 export_blocked` |
| 预览、保存、打开、导出 edge 一致 | 通过 | candidate digest 在保存时重算；换乘保存与 GPX 测试对 edge ID、方向和数据版本做断言 |
| GPX 1.1 与几何校验 | 通过 | 每次生成后执行随包分发的 GPX 1.1 XSD、范围、最小点数、20 km 跳跃与确定性校验；反向首尾坐标有断言 |
| 代表性真实地图抽检 | 通过 | 东莞：4 条线路、24 站，普通线路正反向各 14 edge 且严格镜像；上海：66 条线路、448 站，4 号线环线返回两条需确认候选。两城 GeoJSON 均位于自身 WGS-84 bbox 内 |

## 体验证据

| ROADMAP 标准 | 状态 | 证据 |
|---|---|---|
| 未就绪、导入中、失败、空白、API 错误 | 通过 | 数据状态、持久化进度、错误原因、取消、现有 ready 数据继续可用、列表空白和重试均有界面 |
| 键盘与基础可访问性 | 通过 | 原生表单标签、文本化状态、非颜色提示、原生 modal dialog、Escape、焦点恢复、候选标题聚焦和 reduced-motion |
| 桌面与窄屏核心流程 | 通过 | 7 个核心场景在 desktop Chromium 与 Pixel 7 各运行一次，共 14 个 Playwright 测试 |
| 危险确认与长任务取消 | 通过 | 删除使用显式确认；数据导入可观察、刷新后仍可取消，失败清理 staging 数据 |
| 人工可视复查 | 通过 | 1440×1000 Chromium 实际打开上海行程页，OpenStreetMap 瓦片、真实线路及站点共同显示，页面和控制台无错误 |

## 工程与交付证据

| ROADMAP 标准 | 状态 | 证据 |
|---|---|---|
| lint / type / test / build / Playwright | 通过 | `make check`：40 后端测试、5 个前端测试、84% coverage、Ruff、Mypy、ESLint、Vitest、Vite build；最近一次完整 `make e2e`：14/14 |
| 单一生产入口 | 通过 | `make start` / `scripts/start.sh` 在 `127.0.0.1` 托管 API 与 SPA；健康检查和 5 个 SPA 深链均返回 200 |
| 迁移 | 通过 | 空库升级、`alembic check`、`downgrade -1`、再次 `upgrade head` 通过 |
| 日志轮转 | 通过 | 生产应用日志位于数据目录，5 MiB × 3，测试验证幂等配置；不记录 CSV 内容、行程或输入目录 |
| 备份恢复 | 通过 | 在线 SQLite backup、manifest SHA-256、恢复前安全副本、原子替换和恢复后 `integrity_check=ok` 已演练 |
| 安装、导入、备份、迁移、Fog 说明 | 通过 | `README.md` 与 `docs/DEVELOPMENT.md` 包含从新环境到发布检查的命令和注意事项 |
| 大型真实城市性能基准 | 通过 | 本机暖运行中，上海完整地图响应 812,671 字节、66 线路/448 站，耗时 11.6 ms；“宜山路”站点搜索耗时 8.7 ms。结果用于本机回归基线，不承诺跨机器一致 |
| Fog of World 实际兼容抽检 | 通过 | 2026-08-21 用户确认 V1.0 GPX 在实际安装的 Fog of World 中手动导入通过 |

## 已执行命令

```text
make check
make e2e
scripts/validate_cptond.py <ScienceDB目录> --runtime <隔离目录>
真实 API 地图 / 正反向 / 环线 / journey + coverage GPX 抽检
alembic upgrade head
alembic check
alembic downgrade -1
alembic upgrade head
scripts/start.sh + /healthz 和 SPA 深链检查
scripts/backup.py + scripts/restore.py + PRAGMA integrity_check
Fog of World 实际设备手动导入 V1.0 GPX
```

## 真实数据证据

- ZIP SHA-256：`8ddc522e15a1d228b3dae18745de3891a14c66d1f9032c19215a71c49805b5d0`。
- 解压文件审计 checksum：`552d8e7e8d52c62fdebd96babe32b55c2fedbba67fca5eb0abc30115985e9df2`；重复审计一致。
- 正式本地运行库：46 城、992 线路、7,267 个空间去重站点、992 方向变体，`integrity_check=ok`；导入前备份已生成。
- 东莞反向样例：东莞火车至虎门火车，14 edge、36,915.27 m；正反向 edge 序列互逆，反向标记全部为真。
- 上海环线样例：4 号线内圈 26 站，两个候选分别为 17,665.63 m 与 16,215.98 m，状态为 `needs_review`。
- journey GPX：2 tracks、2 segments、2,367 points、118,963 bytes，SHA-256 `af4de81a82578763e75ef9f01a37860a43e33fe3afb8bed61c86cda58191d6d0`。
- coverage GPX：1 track、2 segments、2,367 points、118,890 bytes，SHA-256 `a63ca16295534d9ce0e658354a10742ce573d0df6aef785dd769dfb9949c6692`。

## v1.0 验收关闭

自动质量门禁、真实数据抽检与 [`FOG_ACCEPTANCE.md`](FOG_ACCEPTANCE.md) 所要求的第三方应用手动导入均已有通过证据。根据用户 2026-08-21 的明确验收确认，v1.0 goal 可以标记为 complete。
