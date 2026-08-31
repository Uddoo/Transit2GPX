# 系统架构

## 1. 架构目标

Transit2Fog 采用本地单体服务配合浏览器前端。前端负责录入、审核和地图交互；后端统一负责数据导入、匹配、拓扑解析、持久化和 GPX 生成。所有路径规则只在后端实现，避免前后端结果不一致。

```text
┌──────────────────────────────────────────────┐
│ React + TypeScript                           │
│ 行程 │ 添加 │ CSV 审核 │ 导出 │ 数据与设置   │
└───────────────────────┬──────────────────────┘
                        │ REST / GeoJSON
┌───────────────────────▼──────────────────────┐
│ FastAPI                                      │
│ API │ Services │ Tasks │ Matcher │ Resolver  │
└───────────────────────┬──────────────────────┘
                        │ SQLAlchemy
┌───────────────────────▼──────────────────────┐
│ SQLite                                       │
│ 业务表 │ FTS5 │ RTree │ WKB 几何 │ 迁移版本  │
└───────────────────────┬──────────────────────┘
                        │ 一次性/可重复导入
┌───────────────────────▼──────────────────────┐
│ CPTOND routes + stops（segments 仅校验/兜底）│
└──────────────────────────────────────────────┘
```

铁路扩展仍保持 FastAPI 为唯一前端 API，但在启用铁路能力时增加 OpenRailRouting loopback sidecar：

```text
React + TypeScript
        │ REST / GeoJSON
FastAPI / Provider facade
        ├── MetroProvider → CPTOND edge / SQLite
        └── RailwayProvider → OpenRailRouting sidecar
                                  │
                                  └── OSM PBF + versioned graph cache
```

sidecar 不是 metro-only 模式的启动依赖。铁路图未安装、建图中或服务不可用时，只禁用铁路路径计算，不影响现有地铁流程。详细设计见 [`RAILWAY.md`](RAILWAY.md)。

## 2. 技术栈

| 层 | 选择 | 责任 |
|---|---|---|
| Web UI | React、TypeScript、Vite | 页面、表单、状态和构建产物 |
| 地图 | Leaflet、React-Leaflet | 城市线路、站点选择、候选预览 |
| API | FastAPI、Pydantic | REST、上传、下载、契约校验 |
| ORM/迁移 | SQLAlchemy、Alembic | SQLite 模型、事务与 schema 演进 |
| 地理 I/O | GeoPandas、Pyogrio | Shapefile/GeoJSON 读取与 CRS 检查 |
| 几何 | Shapely | 合并、投影点、切线、反转、加密和校验 |
| 坐标 | PyProj | WGS‑84 与局部米制 CRS 互转 |
| 图搜索 | NetworkX | 未指定线路时的换乘候选 |
| 铁路路径 | OpenRailRouting、GraphHopper、自定义 Profile | OSM 铁路建图、有序途经点路径、站场/轨距/电气化偏好 |
| XML | lxml | GPX 1.1 构建与 XSD 校验 |
| 测试 | pytest、Vitest、Testing Library、Playwright | 单元、契约、集成和端到端测试 |

## 3. 运行模型

### 开发模式

- Vite 开发服务器提供前端和热更新。
- FastAPI 提供 `/api/v1`。
- Vite 将 `/api` 代理到后端。

### 生产模式

1. `frontend/dist` 由 Vite 构建。
2. FastAPI 在 API 路由之后托管静态文件和 SPA fallback。
3. 单一命令启动 `http://127.0.0.1:8765`。
4. 数据库、缓存与日志位于可配置的应用数据目录，不写入源码目录。

铁路模式由 FastAPI 生命周期内的 supervisor 启动 OpenRailRouting Java sidecar，端口只绑定 `127.0.0.1`。启动前验证 active selector、graph metadata、PBF SHA-256、Profile/commit 身份；已有匹配进程只复用不接管，自启动进程在退出时回收并把输出写入应用数据日志。sidecar 缺失不得阻止地铁模式启动。PBF 与 `graph-cache/<version>` 位于应用数据目录，不提交源码仓库。

发布包由 PyInstaller 封装 production SPA、API、迁移、地理运行库和铁路配置，可选内置固定 sidecar JAR，但不内置大型 PBF、graph cache 或用户数据。Windows 生成用户级 ZIP 安装目录，macOS 生成 `.pkg`/`.tar.gz`；启动器先执行 Alembic，再打开 loopback Web UI。

生产服务默认不得监听 `0.0.0.0`。若未来允许局域网访问，必须作为显式配置并重新评估认证与 CSRF 风险。

## 4. 后端模块边界

建议包结构：

```text
backend/app/
├── api/              # FastAPI routers、请求/响应 schema
├── core/             # 配置、日志、错误、应用生命周期
├── db/               # engine、session、ORM、迁移集成
├── services/         # 查询聚合、空间过滤、导入任务用例
├── tasks/            # SQLite 持久化任务队列与恢复执行器
├── domain/           # 不依赖 FastAPI/SQLAlchemy 的领域类型
├── importers/        # CPTOND 发现、读取、规范化、质量门禁
├── geometry/         # CRS、edge 构建、加密、连接与校验
├── matching/         # 城市/线路/站点名称规范化和候选评分
├── routing/          # 线路内与换乘候选解析
├── providers/        # Metro/Railway/Timetable Provider 边界
├── rail/             # 铁路站点、sidecar client、候选评分与图版本
├── journeys/         # 行程事务和重算策略
└── export/           # 轨迹组装、GPX、XSD 校验
```

约束：

- `domain` 不引用 Web 或数据库框架。
- `geometry` 输入输出显式标记坐标系和 `(lon, lat)` 约定。
- API 只处理 HTTP schema 和错误映射；批量查询、RTree 过滤与长任务编排进入 `services`。
- 导出只读取已保存的 `journey_leg_edge`，不临时重新规划。
- 铁路导出只读取已保存的 `rail_journey_edge_snapshot`，不临时调用 sidecar。
- Provider 必须输出同一候选协议：版本、摘要、有序来源引用、完整几何、评分和警告。

## 5. 前端模块边界

```text
frontend/src/
├── app/              # router、providers、全局 shell
├── api/              # 生成/手写的类型化 API client
├── features/
│   ├── data-setup/
│   ├── journey-editor/
│   ├── csv-import/
│   ├── journey-list/
│   └── gpx-export/
├── components/       # 通用可访问组件
├── map/              # Leaflet 适配层与坐标转换边界
└── styles/           # tokens、全局样式、响应式规则
```

服务端状态使用查询缓存管理；未提交表单/审核选择保留在对应 feature 内。五个顶层业务路由均通过 `React.lazy`/`Suspense` 按需加载，构建 manifest 门禁保证它们保持独立 dynamic entry，并限制主入口体积。不得复制一套线路拓扑到前端自行解析。

## 6. 数据导入流水线

```text
发现输入文件
  → 读取元数据与字段审计
  → CRS 统一为 EPSG:4326
  → 城市/线路/站名规范化
  → route 与 stop 关联
  → 规范站点聚类
  → 线路几何整理与方向判断
  → 站点投影、相邻 edge 切割
  → segments/长度/误差交叉校验
  → FTS5、RTree 与简化地图几何
  → 质量门禁
  → 单事务发布数据版本
```

导入使用 staging 表或临时数据库。只有整版处理完成后才切换为可用版本，避免用户看到半导入状态。

CPTOND 与铁路 PBF 导入先写入 `app_task`，再由单线程 daemon 执行器领取。任务在 SQLite 中记录 queued/running/succeeded/failed/cancelled、尝试次数和错误摘要；服务启动时把遗留 running 任务恢复为 queued。CPTOND 恢复前会清理未完成城市后从同一 checksum 重新执行，铁路索引则按不可变 PBF 身份重建。进程崩溃不会把任务仅留在内存队列中。

## 7. 几何与拓扑

### 7.1 非环线

1. 合并可连通的 MultiLineString；不可连通则失败。
2. 以线路中心创建局部 AEQD 米制 CRS。
3. 按源 sequence 排序站点并投影到线路。
4. 依据投影 measure 的中位增量判断几何方向。
5. measure 反复增减超过容差时进入环线/支线/人工审核。
6. 使用相邻 measure 的 substring 构建 `route_edge`。
7. 保存 WGS‑84 WKB、米制长度、端点投影误差和 bbox。

### 7.2 环线与支线

环线不能沿单一线性 measure 直接裁剪。系统分别构造两个方向的有序 edge 环，并利用 `direction`、`via_station` 和 route variant 过滤。支线作为不同 `route_variant` 保存；起终点同时落入多个变体时返回多个候选。

### 7.3 未指定线路

使用 `(station_id, line_id)` 状态图：乘车 edge 保持在线路状态内，换乘 edge 在同站不同线路状态间连接。搜索返回少量候选供审核，不自动把最短路径当成用户历史。

## 8. 一致性与可复现性

- 数据版本由来源版本、捕获日期、输入校验和和 importer schema 共同标识。
- 路径候选包含有序 edge ID 和方向；保存时完整复制到 `journey_leg_edge`。
- 候选确认应检查版本/摘要，拒绝提交过期候选。
- 新数据版本不会原地修改旧 edge；行程迁移是显式操作。
- GPX 导出记录使用的数据版本集合，并按稳定排序输出。
- 铁路候选摘要同时包含 OSM 数据版本、graph/Profile 版本、有序站序、来源引用和几何哈希。
- GraphHopper 内部 edge ID 只允许作为短期诊断信息；确认后的铁路行程保存完整 WGS‑84 几何快照。
- OSM 或 Profile 更新在新目录构建图并运行固定样本，验收后原子切换；历史快照不随新图变化。

## 9. 质量门禁

线路进入 `ready` 前至少满足：

- CRS 已识别并正确转为 EPSG:4326。
- 经度在 `[-180, 180]`，纬度在 `[-90, 90]`。
- route/stop 关联不含未解释的跨城市数据。
- 相邻站 edge 非空、至少两个不同点、长度大于零。
- 站点投影误差不超过配置阈值；超过警告阈值需报告。
- edge 顺序连通，正反方向可逆。
- 非环线的 station sequence 与 measure 基本单调。
- 质量状态和所有 flags 被持久化。

铁路图进入 `ready` 前还必须满足：

- PBF checksum、数据时间、提取范围和 ODbL 信息完整。
- OpenRailRouting 与 Profile 版本已固定，可重复构建同一图。
- 跨提取边界的代表性铁路保持连通；省界裁剪断点不得静默忽略。
- 固定高速、普速、枢纽和替代路径样本可生成候选，且废弃/施工轨道不会进入可提交候选。
- sidecar 只监听 loopback，超时和无路径有稳定错误码。

## 10. 安全与隐私

- 上传文件名不作为磁盘路径；临时文件名由应用生成。
- 限制 CSV 和空间数据上传大小、行数和解压后体积。
- XML 校验禁用外部实体与不必要的网络解析。
- 下载响应对文件名进行清理，防止 header 注入。
- 日志不记录完整乘车历史、上传内容或本地绝对路径。
- 数据库写操作均使用事务；导入取消后清理 staging 数据。
- FTS5/RTree 由触发器同步；铁路站名搜索走 `rail_station_fts`，地图视口先经 `station_spatial` 与 `route_edge_spatial` 缩小候选。

## 11. 目标仓库结构

```text
transit2fog/
├── README.md
├── ATTRIBUTION.md
├── docs/
├── backend/
│   ├── app/
│   ├── migrations/
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   ├── tests/
│   └── package.json
├── fixtures/         # 小型、可授权的合成/裁剪测试数据
├── scripts/          # 开发、导入、构建和发布入口
├── rail-routing/     # Profile、sidecar 配置与版本清单；不含 PBF/graph cache
└── Makefile          # 或等价的跨平台任务入口
```
