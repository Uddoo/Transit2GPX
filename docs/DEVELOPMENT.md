# 开发与运行

## 环境

- macOS 作为首个支持平台。
- Node.js 22+、npm 10+。
- `uv` 0.9+；项目使用 Python 3.11+，由 uv 管理。

## 首次安装

```bash
make setup
```

该命令会：

1. 根据 `backend/uv.lock` 创建 Python 环境。
2. 根据 `frontend/package-lock.json` 安装前端依赖。

## 开发

```bash
make dev
```

- 前端：`http://127.0.0.1:5173`
- API：`http://127.0.0.1:8765`
- API 文档：`http://127.0.0.1:8765/api/docs`

脚本统一启动两个进程，并在退出时清理后端子进程。

## 生产模式

```bash
make start
```

命令会构建前端、运行 Alembic，然后由 FastAPI 在 `http://127.0.0.1:8765` 同时托管 API 和 SPA。默认不监听局域网地址。

## 质量检查

```bash
make check
make e2e
```

`make check` 包含后端 Ruff、Mypy、pytest，以及前端 ESLint、Vitest 和生产构建。`make e2e` 使用 Playwright 在桌面 Chromium 和移动 Chromium 运行核心流程。

## 应用数据

默认应用数据目录由 `platformdirs` 按操作系统确定。可使用以下变量覆盖：

```bash
TRANSIT2FOG_DATA_DIR=/absolute/path/to/app-data
TRANSIT2FOG_DATABASE_URL=sqlite:////absolute/path/to/transit2fog.sqlite3
```

本地数据库、完整 CPTOND 数据、导出 GPX 和用户行程都不提交到仓库。

既有安装可继续使用 `METRO2FOG_*` 环境变量和 `metro2fog.sqlite3`；新名称优先，检测到旧数据库时会原位使用，不自动复制或删除用户数据。

生产模式会在应用数据目录的 `logs/transit2fog.log` 写入应用级诊断日志；单个文件上限 5 MiB，最多保留 3 个轮转副本。日志只记录任务编号、错误类型等运行信息，不记录 CSV 内容、完整乘车历史或用户填写的数据目录路径。

### 地图配置与隐私

```bash
TRANSIT2FOG_MAP_TILES_ENABLED=true
TRANSIT2FOG_MAP_TILE_URL=https://tile.openstreetmap.org/{z}/{x}/{y}.png
TRANSIT2FOG_MAP_TILE_ATTRIBUTION='&copy; OpenStreetMap contributors'
TRANSIT2FOG_MAP_MAX_ZOOM=19
```

默认 OpenStreetMap Standard 瓦片仅随当前交互视口加载，不预取、不批量下载。瓦片请求会把视口范围和常规网络信息发送给外部服务，但不会附带行程记录。离线或严格本地模式可设置 `TRANSIT2FOG_MAP_TILES_ENABLED=false`；此时已导入的 CPTOND 线路和站点仍会显示在无底图画布上。

## 导入真实地铁数据

首选 CPTOND-2025 官方 v2；当 Figshare 下载受限时，也可使用同一研究团队发布在 Science Data Bank、基于 CPTOND-2025 构建的 46 城地铁时序数据集。两种格式共用同一个目录导入入口，但会分别保留来源 DOI 和许可证。

### CPTOND-2025 v2

1. 从 [CPTOND-2025 Figshare 页面](https://doi.org/10.6084/m9.figshare.29377427)获取 v2 数据并完整解压到仓库外目录。
2. 保留 Shapefile 文件组，不要只复制 `.shp`。每组至少需要 `.shp`、`.shx`、`.dbf`、`.prj`。
3. 启动应用，打开“数据与设置”，填写解压目录的绝对路径。
4. 点击“导入数据目录”，等待状态变为“真实地铁数据已就绪”。
5. 检查可用线路、阻断线路和阻断方向；阻断数据不会进入地图路径候选或 GPX 导出。

支持以下两种布局，文件可位于输入目录任意子层级：

```text
CPTOND-2025/
  metro_routes.shp
  metro_routes.shx
  metro_routes.dbf
  metro_routes.prj
  metro_stops.shp
  metro_stops.shx
  metro_stops.dbf
  metro_stops.prj
```

或城市级文件对：

```text
CPTOND-2025/
  city-a/..._metro_routes.shp
  city-a/..._metro_stops.shp
  city-b/..._metro_routes.shp
  city-b/..._metro_stops.shp
```

导入器会先审计字段、CRS、sidecar 与 SHA-256，再统一转换为 EPSG:4326 并构建 route-aware edges。重复导入相同版本与 checksum 会复用已有数据版本。
导入进度按城市持久化；刷新设置页后仍可观察或取消。新版本导入期间旧 ready 数据继续提供查询，失败或取消会清理新版本的 staging 城市；只有全部处理结束且至少一个城市通过质量门禁后，才原子切换 active 数据版本。

### Science Data Bank 时序数据集

1. 打开[中国城市地铁修建时序数据集（1971–2025）](https://doi.org/10.57760/sciencedb.33335)，下载并完整解压数据文件。
2. 保留三个 Shapefile 及其 `.shx`、`.dbf`、`.prj` sidecar：

```text
Metro-Timeline-1971-2025/
  metro_routes.shp
  metro_routes_segment_timeline.shp
  metro_stations_timeline.shp
```

站点文件名也兼容 `metro_stops_timeline.shp`。导入器使用 `seg_seq`、`s_stop_id` 和 `e_stop_id` 重建每个方向的站序；真实包的线路主表没有 `route_id`，适配器会用城市与完整方向名从分段 `s_route_id` 回填唯一 ID。若同一名称对应零个或多个 ID，便不会猜测。分段中的零长度同站方向锚点会被忽略，站点坐标优先取自站点图层，缺失时才退回分段端点；其余分段不连续方向仍留在质量门禁之外。

该数据集页面标注公开访问、9,194,749 字节及 CC BY-NC-SA 4.0。应用会把 Science Data Bank DOI、该许可证和 `cptond-v2.3` 适配器版本写入数据版本记录，不会误标为 Figshare 原包。

2026-08-21 的真实包验收记录：ZIP SHA-256 为 `8ddc522e15a1d228b3dae18745de3891a14c66d1f9032c19215a71c49805b5d0`；解压文件审计 checksum 为 `552d8e7e8d52c62fdebd96babe32b55c2fedbba67fca5eb0abc30115985e9df2`。共导入 46 城、992 条线路方向和 17,731 条线路站点记录，结果为 992 条可用线路、0 条阻断线路。完整第三方数据和本地验收输出均位于 `.gitignore` 覆盖的 `data/`，不会进入版本库。

发布前可在隔离数据库中执行真实数据机器验收，不会修改现有行程库：

```bash
make validate-real-data CPTOND_DIR=/absolute/path/to/extracted-dataset
```

命令会重复审计 checksum、完整导入，并要求至少找到一座普通线路城市和另一座含环线/支线的城市，输出后续人工地图抽检应使用的城市。若需保留验证库以供排查，可直接运行 `scripts/validate_cptond.py ... --runtime /absolute/path/to/validation-runtime`。

## 构建与运行铁路图

铁路能力额外需要 Java；当前可复现基线使用 Java 21。sidecar、PBF 和 graph 都是可选本地资源，缺失时地铁流程仍可运行。

```bash
make rail-bootstrap
make rail-yangtze-data
make rail-yangtze-graph
make rail-china-data
make rail-china-graph
```

在一个终端启动与图 metadata checksum 一致的 sidecar，在另一个终端运行固定样本并激活：

```bash
./scripts/rail_start.sh china-20260815-r3.1 /absolute/path/china-20260815.osm.pbf
make rail-china-validate
make rail-china-activate
```

图与 sidecar 就绪后，可直接启动同时包含地铁和铁路能力的开发环境：

```bash
make dev-rail
```

普通 `make dev` 仍保持铁路可选并默认关闭；铁路录入页会保留乘车事实输入，并明确提示车站搜索和路径预览为何暂不可用。

FastAPI 使用以下配置读取原子 selector：

```bash
TRANSIT2FOG_RAIL_ENABLED=true
TRANSIT2FOG_RAIL_GRAPH_VERSION=active
TRANSIT2FOG_RAIL_GRAPH_ROOT=/absolute/path/to/graphs
TRANSIT2FOG_RAIL_SIDECAR_URL=http://127.0.0.1:8989
```

切换异常时执行 `make rail-rollback`，然后以 `active` 重启 sidecar。激活脚本会拒绝不匹配的验证报告，resolver 也会在算路前复核 graph/PBF/Profile/commit 身份。更完整的构建和资源基线见 [`rail-routing/README.md`](../rail-routing/README.md)。

## 数据库迁移

```bash
make db-upgrade
```

创建新迁移：

```bash
cd backend
uv run alembic revision --autogenerate -m "describe change"
```

迁移必须同时包含升级/降级路径，并在空数据库和现有测试数据库上验证。

发布前建议用临时目录执行完整迁移演练：

```bash
migration_runtime="$(mktemp -d)"
cd backend
TRANSIT2FOG_ENVIRONMENT=test \
TRANSIT2FOG_DATA_DIR="$migration_runtime/data" \
TRANSIT2FOG_DATABASE_URL="sqlite:///$migration_runtime/data/transit2fog.sqlite3" \
uv run alembic upgrade head
```

随后在 `backend` 目录运行 `uv run alembic check`，并验证 `downgrade base` 后能再次 `upgrade head`。

## 备份与恢复

服务运行时也可使用 SQLite 在线备份：

```bash
uv run --project backend python scripts/backup.py /absolute/path/transit2fog-backup.zip
```

备份 ZIP 只包含数据库快照和带 SHA-256 的 manifest。恢复前先停止 Transit2Fog，防止运行中连接继续写入：

```bash
uv run --project backend python scripts/restore.py /absolute/path/transit2fog-backup.zip --yes
```

恢复流程会检查 ZIP 内容、checksum 和 SQLite `integrity_check`，并在替换前于数据库旁生成 `*.pre-restore-*.bak` 安全副本。不要在确认新数据库正常前删除该副本。

## 导入 Fog of World

1. 在“导出”页选择 journey 或 coverage 模式、行程范围与点间距。
2. 确认预览没有阻断错误后生成 `.gpx`。
3. 将文件传到安装《世界迷雾》的设备，并通过应用当前版本提供的 GPX/KML 导入入口选择该文件。
4. 首次导入建议先用少量行程抽检线路位置和分段，再导入完整 coverage 文件。

Transit2Fog 不伪造时间、高程或速度；若《世界迷雾》版本的菜单名称发生变化，请以其[官方说明](https://fogofworld.app/)为准。
本项目的两份真实数据验收 GPX、安全准备、逐项通过标准和结果模板见 [`docs/FOG_ACCEPTANCE.md`](FOG_ACCEPTANCE.md)。
铁路验收文件与抽查步骤见 [`docs/RAIL_FOG_ACCEPTANCE.md`](RAIL_FOG_ACCEPTANCE.md)。

## 发布前检查清单

```bash
make check
make e2e
make start
```

`make start` 后应验证 `/healthz`、首页及 `/journeys/new`、`/journeys`、`/imports/csv`、`/exports`、`/settings/data` 等 SPA 深链。数据库备份/恢复和 Alembic 升降级也必须至少演练一次。
