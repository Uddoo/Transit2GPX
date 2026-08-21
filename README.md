# Transit2Fog

Transit2Fog 是一个本地优先的中国地铁与国铁轨迹工具：用户按真实乘坐区间选择或导入行程，应用解析对应线路几何、展示候选路径供确认，并导出标准 WGS‑84 GPX 1.1 轨迹文件。

导出的文件使用标准 `<trk>` / `<trkseg>` 轨迹结构，可用于任何支持导入 GPX 1.1 轨迹的地图、户外、旅行记录或轨迹管理应用。《世界迷雾》（Fog of World）只是兼容应用示例之一，并非唯一目标。地铁几何来自 CPTOND；铁路能力组合用户提供的乘车事实、OpenStreetMap 铁路几何与 OpenRailRouting 候选路径。

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
支持 GPX 轨迹导入的应用
```

## 产品原则

- 只补用户实际乘坐的站间区间，不擅自扩展到整条线路。
- 环线、支线、同名站、模糊匹配等歧义必须由用户确认。
- 预览、保存和导出引用同一组不可变 `route_edge`，避免结果漂移。
- 内部存储、GeoJSON 和 GPX 都使用 WGS‑84；米制运算使用局部投影。
- 以标准 GPX 1.1 作为应用间的兼容边界，不依赖目标应用的私有格式或数据库。
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
- [交付路线图](docs/ROADMAP.md)：当前进度、实施阶段、测试矩阵与完成标准。
- [已知限制](docs/KNOWN_LIMITATIONS.md)：当前验收缺口和发布前待办。
- [v1.0 验收审计](docs/V1_AUDIT.md)：逐条完成状态、测试证据与最后外部阻断项。
- [Fog of World 实机验收](docs/FOG_ACCEPTANCE.md)：两份真实数据 GPX 的安全导入步骤、通过标准与结果记录模板。
- [Fog of World 铁路实机验收](docs/RAIL_FOG_ACCEPTANCE.md)：北京南—上海虹桥全国铁路 GPX 的固定哈希、抽查步骤与关闭条件。
- [数据与第三方署名](ATTRIBUTION.md)：CPTOND、Science Data Bank、OpenStreetMap、Geofabrik 与 OpenRailRouting 的署名边界。

## 10 分钟地铁上手

这条路径面向第一次使用项目的人；“10 分钟”不包含第三方数据和依赖的网络下载时间。当前首个支持平台是 macOS，需要 Node.js 22+、npm 10+ 和 `uv` 0.9+。

### 1. 检查并安装环境

```bash
make doctor
make setup
```

`make doctor` 只检查环境，不下载或修改数据；`make setup` 根据锁文件安装 Python 和前端依赖。

### 2. 获取一份地铁数据

任选一个来源，下载后完整解压到仓库外目录：

| 来源 | 适合场景 | 导入时应看到的主文件 |
|---|---|---|
| [CPTOND-2025 v2](https://doi.org/10.6084/m9.figshare.29377427) | 官方完整基线，CC BY 4.0 | `metro_routes.shp`、`metro_stops.shp` |
| [Science Data Bank 46 城时序数据](https://doi.org/10.57760/sciencedb.33335) | Figshare 下载受限时的兼容替代源，CC BY-NC-SA 4.0 | `metro_routes.shp`、`metro_routes_segment_timeline.shp`、`metro_stations_timeline.shp` |

不要只复制 `.shp`。每组 Shapefile 必须同时保留同名的 `.shx`、`.dbf`、`.prj`；文件可以位于所选目录的任意子层级。

### 3. 启动并导入

```bash
make dev
```

1. 打开 `http://127.0.0.1:5173/settings/data`。
2. 在“地铁数据”中填写解压目录的绝对路径，点击“导入数据目录”。
3. 等待状态变为“真实地铁数据已就绪”，并确认阻断线路数量符合预期。
4. 如果导入失败，先检查 Shapefile sidecar、CRS 和页面中的质量报告。

### 4. 创建行程并导出 GPX

1. 打开“添加行程”，选择城市、线路、起点和终点。
2. 预览候选；环线、换乘或模糊结果需要人工确认。
3. 保存后打开“导出”，先用少量行程生成 journey GPX 抽检，再按需生成 coverage GPX。
4. 将 GPX 导入目标轨迹应用，确认轨迹没有错误直线或明显跳点；例如可使用《世界迷雾》。

生产模式使用 `make start`，由单一 FastAPI 服务在 `http://127.0.0.1:8765` 托管 API 和前端。行程页默认使用 OpenStreetMap 在线底图；可通过环境变量关闭或替换为合规的自托管瓦片服务。更完整的数据格式、隔离验证和故障排查见[开发与运行](docs/DEVELOPMENT.md)。

## 铁路最短可用路径

铁路数据下载已经脚本化，但首次使用还需要构建 OpenRailRouting sidecar 和本地图。Java 17+ 可以运行，Java 21 是当前验证基线；系统 Maven 不是必需项，脚本会下载并校验固定版本。

### 1. 先选择图范围

| 方案 | 固定数据 | 验证集合 | 建议资源 | 适合场景 |
|---|---|---|---|---|
| 长三角轻量图 | 上海、江苏、浙江、安徽合并 PBF，参考成品约 223 MB | 4 条跨省/高普速线路 | 至少 3 GB 可用磁盘、4 GB 可用内存 | 首次体验、开发调试 |
| 全国完整图 | 中国 PBF 约 1.58 GB，graph 约 187 MB | 8 条全国代表线路 | 至少 5 GB 可用磁盘、4 GB 可用内存 | 全国行程、正式使用 |

全国图在验收机器上建图约 166 秒、峰值 RSS 约 1.46 GB；首次 bootstrap 还会下载并编译固定版本依赖，实际耗时取决于网络和机器。以上是保守准备建议，不是跨平台最低配置承诺。

### 2. 首次准备

先检查核心和铁路环境：

```bash
make setup
make doctor-rail
make rail-bootstrap
```

选择长三角轻量图：

```bash
make rail-yangtze-data
make rail-yangtze-graph
```

或者选择全国完整图：

```bash
make rail-china-data
make rail-china-graph
```

下载支持断点续传，并按仓库固定 manifest 校验摘要；PBF、graph 和构建产物都保存在被忽略的 `data/` 目录。

### 3. 用两个终端启动

长三角路径：

```bash
# 终端 A：保持 sidecar 运行
make rail-yangtze-start

# 终端 B：首次运行时验证并激活，然后启动应用
make rail-yangtze-activate
make dev-rail
```

全国路径只需替换命令名：

```bash
# 终端 A
make rail-china-start

# 终端 B
make rail-china-activate
make dev-rail
```

`*-activate` 会先运行对应的固定样本验证，再原子切换 `active`。已经验证并激活过同一图版本时，终端 B 可直接运行 `make dev-rail`。应用位于 `http://127.0.0.1:5173`；sidecar 只监听 `127.0.0.1:8989`，不要直接暴露给局域网。完整的版本锁定、区域图、自定义 PBF 和回滚说明见 [`rail-routing/README.md`](rail-routing/README.md)。

如果已有图位于旧验收目录或其他自定义位置，请在两个终端先设置相同路径，再运行上述命令；`make doctor-rail` 会显示它实际检查到的 JAR 和 `active` 图：

```bash
export RAIL_WORK_DIR=/absolute/path/to/rail-work
export RAIL_GRAPH_ROOT=/absolute/path/to/graphs
make doctor-rail
```

## 数据与标准基线

- CPTOND-2025：以 2025 年 6 月数据快照为首个数据源；Figshare v2 标注 CC BY 4.0，并描述覆盖 46 个城市的地铁系统。
- Science Data Bank 时序数据集：基于 CPTOND-2025 的 46 城地铁数据，补充 1971–2025 开通时序；页面标注 CC BY-NC-SA 4.0，作为 Figshare 受限时的兼容来源。
- 国铁几何：Geofabrik 提供的 OpenStreetMap 中国或省级 PBF，按 ODbL 1.0 使用并保留 `© OpenStreetMap contributors` 署名。
- 铁路路径引擎：固定提交的 OpenRailRouting/GraphHopper fork；运行时图版本、自定义中国国铁 Profile 和 PBF checksum 共同构成身份。
- GPX：导出遵循 Topografix GPX 1.1，坐标基准为 WGS‑84。
- GPX 兼容性：目标应用需要支持 GPX 1.1 的 `<trk>` / `<trkseg>` 轨迹；点数限制、简化规则和重复轨迹处理以各应用为准。
- Fog of World：兼容应用示例；官网说明支持导入 GPX/KML 轨迹。

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
- [兼容应用示例：Fog of World](https://fogofworld.app/)
