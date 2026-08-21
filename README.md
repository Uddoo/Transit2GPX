# Transit2Fog

Transit2Fog 是一个本地优先的中国地铁与国铁轨迹工具：用户按真实乘坐区间选择或导入行程，应用解析对应线路几何、展示候选路径供确认，并导出可导入《世界迷雾》（Fog of World）的 WGS‑84 GPX 1.1 文件。

中国铁路、高铁和动车扩展的 R0–R3 已完成。铁路能力组合用户提供的乘车事实、OpenStreetMap 铁路几何与 OpenRailRouting 候选路径；2026-08-21，用户确认铁路 GPX 已在 Fog of World 中手动导入成功，产品随即由 **Metro2Fog** 迁移为 **Transit2Fog**。

```text
CPTOND 地铁数据
       ↓
本地、带线路语义的地铁拓扑库
       ↓
地图选站 / 手动录入 / CSV 导入与审核
       ↓
路径候选、歧义确认、行程保存
       ↓
GPX 1.1（WGS‑84）
       ↓
Fog of World
```

## 当前状态

设计基线与 M0–M7 纵向功能已经落盘：真实底图、CPTOND 导入、线路内/换乘候选、行程管理、CSV 审核、GPX 1.1 导出及发布运维均已有可运行实现。后端 lint/type/test、前端 lint/test/build 和桌面/窄屏 Playwright 核心流程已纳入统一检查。

**v1.0 已完成验收**：Science Data Bank 的 46 城真实数据已完成整包导入，东莞普通线路与上海环线的地图、正反向候选和两种 GPX 已通过抽检；用户也已确认 V1.0 GPX 在实际安装的 Fog of World 中手动导入通过。完整第三方数据仍不会提交进仓库。验收证据见 [v1.0 验收审计](docs/V1_AUDIT.md)，产品边界见[已知限制](docs/KNOWN_LIMITATIONS.md)。

**铁路轨迹 R0–R3 已完成代码、自动化与实机验收**。当前实现包括长三角和全国真实图、三套中国国铁 Profile、共享 Provider/行程模型、车站搜索和有序站序、最多三个可解释候选、人工确认、不可变铁路快照、统一 CSV、混合 GPX、版本比较、显式重算、原子切换与回滚。全国图包含 645,361 个节点、742,281 条边，18,490 个车站索引；8 条全国代表性线路已通过固定样本验证，铁路 GPX 也已通过 Fog of World 手动导入。设计、运维和验收证据见[国铁轨迹扩展设计](docs/RAILWAY.md)。

本项目的当前完成基线是已验收的地铁 v1.0 加铁路 R0–R3，而不是只完成几何算法原型。

## 产品原则

- 只补用户实际乘坐的站间区间，不擅自扩展到整条线路。
- 环线、支线、同名站、模糊匹配等歧义必须由用户确认。
- 预览、保存和导出引用同一组不可变 `route_edge`，避免结果漂移。
- 内部存储、GeoJSON 和 GPX 都使用 WGS‑84；米制运算使用局部投影。
- 默认仅监听 `127.0.0.1`，乘车历史和导入文件不离开本机。
- 原始数据必须带版本、校验和、许可与质量记录；有问题的线路不得进入可导出状态。

## 文档索引

- [产品需求](docs/PRODUCT.md)：目标用户、完整流程、功能与验收要求。
- [系统架构](docs/ARCHITECTURE.md)：技术栈、模块边界、运行与数据流。
- [数据与 API 契约](docs/DATA_API.md)：数据库模型、CSV、REST、GPX 和几何约束。
- [国铁轨迹扩展设计](docs/RAILWAY.md)：铁路数据源、Provider、模型、候选、API、GPX 与实施顺序。
- [关键设计决策](docs/DECISIONS.md)：已确定方案、理由与代价。
- [视觉与交互设计系统](docs/DESIGN_SYSTEM.md)：概念图、tokens、组件和响应式规则。
- [开发与运行](docs/DEVELOPMENT.md)：安装、开发、生产启动和质量检查。
- [交付路线图](docs/ROADMAP.md)：实施阶段、测试矩阵与 v1.0 完成标准。
- [已知限制](docs/KNOWN_LIMITATIONS.md)：当前验收缺口和发布前待办。
- [v1.0 验收审计](docs/V1_AUDIT.md)：逐条完成状态、测试证据与最后外部阻断项。
- [Fog of World 实机验收](docs/FOG_ACCEPTANCE.md)：两份真实数据 GPX 的安全导入步骤、通过标准与结果记录模板。
- [Fog of World 铁路实机验收](docs/RAIL_FOG_ACCEPTANCE.md)：北京南—上海虹桥全国铁路 GPX 的固定哈希、抽查步骤与关闭条件。
- [数据与第三方署名](ATTRIBUTION.md)：CPTOND、Science Data Bank、OpenStreetMap、Geofabrik 与 OpenRailRouting 的署名边界。

## 快速开始

```bash
make setup
make dev
```

开发界面位于 `http://127.0.0.1:5173`。生产模式使用 `make start`，由单一 FastAPI 服务托管 API 和前端。

首次启动后打开“数据与设置”，输入解压后的地铁数据目录绝对路径并开始导入。应用接受全国级 `metro_routes.shp` + `metro_stops.shp`、成对的城市级 CPTOND 文件，也接受 Science Data Bank 的 `metro_routes.shp` + `metro_routes_segment_timeline.shp` + `metro_stations_timeline.shp`；每个 Shapefile 必须保留 `.shx`、`.dbf`、`.prj` 等 sidecar 文件。

行程页地图使用 OpenStreetMap 作为真实地理底图，地铁线路和站点则只来自本机已通过质量门禁的 CPTOND 数据。在线底图可在环境变量中关闭或替换为自托管瓦片服务。

## 数据与标准基线

- CPTOND-2025：以 2025 年 6 月数据快照为首个数据源；Figshare v2 标注 CC BY 4.0，并描述覆盖 46 个城市的地铁系统。
- Science Data Bank 时序数据集：基于 CPTOND-2025 的 46 城地铁数据，补充 1971–2025 开通时序；页面标注 CC BY-NC-SA 4.0，作为 Figshare 受限时的兼容来源。
- 国铁几何：Geofabrik 提供的 OpenStreetMap 中国或省级 PBF，按 ODbL 1.0 使用并保留 `© OpenStreetMap contributors` 署名。
- 铁路路径引擎：固定提交的 OpenRailRouting/GraphHopper fork；运行时图版本、自定义中国国铁 Profile 和 PBF checksum 共同构成身份。
- GPX：导出遵循 Topografix GPX 1.1，坐标基准为 WGS‑84。
- Fog of World：官网说明支持导入 GPX/KML 轨迹。

原始 CPTOND 数据不直接提交到仓库。应用应提供可复现的导入流程，并在界面和导出元数据中保留数据署名。

## 参考资料

- [CPTOND-2025 数据集](https://figshare.com/articles/dataset/CPTOND-2025/29377427)
- [CPTOND 项目](https://github.com/jean89091515/CPTOND)
- [CPTOND-2025 论文](https://doi.org/10.1038/s41597-025-06505-4)
- [中国城市地铁修建时序数据集（1971–2025）](https://doi.org/10.57760/sciencedb.33335)
- [OpenRailRouting](https://github.com/geofabrik/OpenRailRouting)
- [Geofabrik 中国 OSM 下载](https://download.geofabrik.de/asia/china.html)
- [OpenStreetMap copyright 与 ODbL](https://www.openstreetmap.org/copyright)
- [GPX 1.1 Schema](https://www.topografix.com/gpx/1/1/)
- [Fog of World 官网](https://fogofworld.app/)
