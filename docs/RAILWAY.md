# 国铁轨迹扩展设计

状态：R0–R3 实现、自动化验收、Fog of World 铁路实机导入与 Transit2Fog 迁移完成。最后更新：2026-08-21。

本文件定义原 Metro2Fog v1.0 之后的中国铁路、高铁、动车轨迹能力。铁路纵向切片已通过验收，面向用户的产品名、包名、默认数据目录和 GPX creator 已升级为 **Transit2Fog**；旧名称仍只用于兼容既有安装。

## 1. 目标与边界

铁路扩展用于把用户已经乘坐的国铁区间还原为可审核、可复现的 WGS‑84 轨迹，并继续导出 Fog of World 可导入的 GPX 1.1。它不是售票、实时列车查询或导航服务。

铁路轨迹由三类信息共同确定：

```text
乘车事实
日期 + 车次 + 上下车站 + 有序经停站
                  │
                  ▼
基础设施几何
OpenStreetMap / Geofabrik PBF
                  │
                  ▼
铁路路径计算
OpenRailRouting + 中国国铁 Profile
                  │
                  ▼
1～3 个候选 + 用户确认
                  │
                  ▼
不可变几何快照 → GPX 1.1
```

支持范围包括 G/C/D 动车组、Z/T/K 等普速列车、普通无字头列车、城际铁路和具备国铁轨道语义的市域铁路。地铁继续由 CPTOND Provider 负责，不改用 OSM 重算已经验收的 v1.0 行程。

第一版铁路能力明确不做：

- 内置 12306 爬虫或假定存在可长期使用的公开时刻表 API。
- 缓存高德查询结果并据此构建离线铁路数据库或永久 GPX。
- 仅凭车次前缀推断唯一轨道。
- 在不知道站台和股道时声称还原精确站内进路。
- 根据始发、到达时间伪造每个 GPX 点的时间戳。

## 2. 已确认的架构选择

### 2.1 共享行程，不复制一套 `train_journey`

地铁和铁路共用现有 `journey` 聚合、行程列表、CSV 审核和导出流程。`journey_leg` 增加 `transport_mode = metro | rail`，铁路特有字段放入一对一或一对多明细表。

不新建与 `journey` 平行的顶层 `train_journey`，否则日期、备注、生命周期、导出筛选和事务规则会出现两套实现。

### 2.2 OpenRailRouting 是可选 sidecar

地铁模式继续只需要 FastAPI、SQLite 和前端。启用铁路功能时，应用额外启动仅监听 loopback 的 OpenRailRouting Java/GraphHopper 服务：

```text
React + Leaflet
       │ REST
FastAPI / Provider facade
       ├── CPTOND MetroProvider → SQLite
       └── OSM RailwayProvider → OpenRailRouting sidecar
                                      │
                                      └── graph-cache/<version>/
```

FastAPI 是唯一面向前端的 API。前端不得直接调用 sidecar。sidecar 的不可用、建图中、图版本不匹配和超时必须成为可解释状态，不能回退为普通直线或道路路径。

### 2.3 不依赖 GraphHopper 内部 edge ID

GraphHopper 内部 edge ID 会随导入和版本变化，不能作为历史行程的永久主键。候选可以携带短期 provider edge reference，但用户确认时必须固化：

- OSM/Geofabrik 数据版本和图版本；
- 可获得时的 OSM way/node 来源引用；
- 有序 WGS‑84 完整几何；
- 方向、连续分组和几何 SHA‑256；
- 路径评分明细与警告。

地图预览、重新打开和 GPX 导出都读取这份不可变快照，导出时不得重新请求 OpenRailRouting。

### 2.4 时刻表 Provider 首版只接受用户事实

第一版只实现：

```text
ManualTimetableProvider
CsvTimetableProvider
```

未来只有在获得明确授权、可稳定版本化的数据源后，才增加 `AuthorizedTimetableProvider`。第三方查询页面可以由用户人工核对，但应用不自动抓取或永久保存受限制的服务结果。

## 3. 数据源与许可

铁路主几何来自 Geofabrik 提供的 OpenStreetMap PBF。导入必须记录：

```text
source_url
source_timestamp
pbf_checksum
extract_region
OpenRailRouting commit/version
GraphHopper graph schema/profile version
imported_at
license = ODbL-1.0
```

长三角 POC 使用上海、江苏、浙江、安徽范围。跨省测试必须先合并提取文件并验证边界连通性，或从中国 PBF 用 `complete_ways` 等保全策略裁剪；不能把省界处的裁剪断点误判为铁路断线。

OSM 数据和基于它的路由能力必须显示 `© OpenStreetMap contributors`，并链接 OSM copyright/ODbL 信息。若未来公开分发铁路提取库、图缓存或其他衍生数据库，发布前必须单独完成 ODbL 衍生数据库审查；默认仓库不提交 PBF、graph cache 或全国铁路派生库。完整署名策略见 [`ATTRIBUTION.md`](../ATTRIBUTION.md)。

## 4. Provider 边界

```text
TransitProvider
├── MetroProvider
│   └── CPTONDProvider
└── RailwayProvider
    └── OSMRailInfrastructureProvider

TimetableProvider
├── ManualTimetableProvider
├── CsvTimetableProvider
└── AuthorizedTimetableProvider  # 预留

PathResolver
├── MetroPathResolver
└── NationalRailPathResolver

GPXExporter
└── 按 leg.transport_mode 选择加密与署名策略
```

Provider 输出统一候选协议：数据版本、稳定摘要、完整 GeoJSON、分段来源引用、评分、警告和是否允许提交。铁路 resolver 可以调用 sidecar，地铁 resolver 继续读取 SQLite `route_edge`。

## 5. 逻辑数据模型

以下核心模型已经由 Alembic 迁移和 ORM 约束实现：

```text
rail_dataset_version
  id, source_name, source_url, source_timestamp, pbf_checksum,
  extract_region, graph_version, profile_version, imported_at,
  license, status, quality_flags_json

rail_station
  id, rail_dataset_version_id, osm_type, osm_id,
  name_cn, name_en, normalized_name, pinyin_full, pinyin_initials,
  station_code, city_name, province_name, lon, lat,
  match_status, quality_flags_json

rail_station_alias
  id, station_id, alias, normalized_alias, alias_type, source

journey_leg
  ...existing fields...,
  transport_mode

rail_journey_leg_detail
  journey_leg_id, travel_date, train_no, train_type,
  route_hint, confidence, resolution_status, selected_candidate_digest

rail_journey_stop
  id, journey_leg_id, stop_sequence, station_id, raw_station_name,
  arrival_time, departure_time, is_boarding, is_alighting,
  match_method, match_confidence, locked_by_user

rail_journey_edge_snapshot
  journey_leg_id, order_no, rail_dataset_version_id,
  provider_edge_ref, osm_way_id, from_osm_node_id, to_osm_node_id,
  reversed, continuity_group, distance_m, geometry_wkb,
  geometry_sha256, quality_flags_json
```

铁路外键加入后，现有地铁 `journey_leg` 中的 city/line/variant/route edge 关联改为按 `transport_mode` 校验的可空关系。数据库约束或服务层必须保证每个 leg 恰好使用一类 Provider 快照，不能同时引用地铁 edge 和铁路 snapshot。

短期 `rail_route_candidate` 可以存入有过期时间的候选缓存，也可以使用签名摘要重算校验；无论采用哪种实现，确认后都只信任服务端候选，不能接受前端上传的任意几何。

## 6. 车站匹配与站序

匹配优先级：

1. 人工维护的车站代码映射。
2. 中文站名 + 城市/省份精确匹配。
3. 站名别名精确匹配。
4. 拼音全拼或首字母匹配。
5. OSM `railway=stop` / `public_transport=stop_position`。
6. `railway=station` 几何附近的客运主轨道。
7. 用户在地图上人工选择。

不能只通过删除“站”字生成别名。用户提供的有序站点必须作为路径硬约束，候选必须依次通过：

```text
上车站 → 已知经停站 1 → ... → 已知经停站 N → 下车站
```

逐段求路后还要检查干线连续、枢纽连通、非预期换向和平行线路跳转。

大型枢纽第一版采用标准模式：保存与实际客运走廊一致的代表性通道，不声称精确到站台股道。精细模式推迟到标准模式通过真实样本验收之后。

## 7. 候选与评分

每次最多返回三个可解释候选。基础成本由运行时间/距离与以下规则共同构成：

```text
禁止或阻断：废弃、拆除、施工、轨距明确不兼容、经停站顺序错误
高惩罚：货运专用、yard、siding、spur、crossover、不合理掉头
偏好：车次类型与高速/普速属性匹配、route 关系、用户 route_hint
警告：OSM 关键属性缺失、站点吸附距离过大、跨省图边界可疑
```

G/C/D/Z/T/K 等车次类别只改变偏好，不作为“只允许高铁线/普速线”的硬规则。缺少 OSM 电气化或速度属性时不得轻率禁止路径，应降置信度并展示警告。

初始置信度策略：

| 分数 | 行为 |
|---:|---|
| `>= 0.90` | 默认高亮，仍展示地图并由用户确认 |
| `0.70–0.89` | 必须人工选择候选 |
| `< 0.70` | 不允许提交或导出，需补充站序/线路提示 |

评分明细至少包含站名匹配、有序站覆盖、线路提示、车次兼容、OSM route 关系和距离合理性。权重是可校准产品参数，不能在缺少真实样本时承诺为准确概率。

## 8. CSV 与 API 演进

统一 CSV 采用每行一个 leg，并增加判别字段：

```csv
journey_id,leg_no,mode,travel_date,train_no,train_type,city,line,from_station,to_station,via_stations,route_hint,direction,note
20260820-01,1,rail,2026-08-20,GXXXX,G,,,上海虹桥,杭州东,嘉兴南|桐乡,沪昆高速铁路,,
20260822-01,1,metro,2026-08-22,,,上海,1号线,人民广场,徐家汇,,,,
```

- 旧 CSV 缺少 `mode` 时按 `metro` 处理，保持向后兼容。
- 铁路 `travel_date`、`from_station`、`to_station` 必填；`train_no` 建议填写。
- `via_stations` 按顺序用 `|` 分隔；兼容读取旧字段 `via_station`。
- 只有车次没有日期时不能自动提交；只有起终点时必须人工确认。

现有 `/api/v1/paths/preview` 演进为按 `mode` 判别的请求联合类型。迁移期缺少 `mode` 时仍按地铁请求处理：

```json
{
  "mode": "rail",
  "travel_date": "2026-08-20",
  "train_no": "GXXXX",
  "train_type": "G",
  "from_station_id": 101,
  "to_station_id": 205,
  "via_station_ids": [130, 144],
  "route_hint": "沪昆高速铁路"
}
```

铁路数据管理增加：

```http
GET  /api/v1/rail/data/status
POST /api/v1/rail/data/imports
GET  /api/v1/rail/data/imports/{import_id}
GET  /api/v1/rail/data/compare?from_graph_version=...&to_graph_version=...
GET  /api/v1/rail/stations/search?q=...
POST /api/v1/journeys/{journey_id}/rail-recompute/preview
POST /api/v1/journeys/{journey_id}/rail-recompute
```

行程保存和导出继续复用 `/journeys` 与 `/exports`。候选 digest 必须包含 mode、输入事实、数据/图/Profile 版本、有序来源引用和几何摘要。

## 9. 前端体验

“添加行程”增加地铁/铁路模式切换。铁路首版提供：

1. **车次录入**：日期、车次、上下车站、已知经停站和线路提示。
2. **手动站序**：粘贴多行站名，转换为可排序、可删除、可锁定的站点标签。
3. **地图选线**：选上车站和下车站，展示 1～3 条不同颜色的候选；可添加途经站重新计算。

候选摘要显示距离、高速线比例、主线比例、经停站匹配数、置信度和警告。所有地图操作都要有键盘可达的搜索/站序替代方案。

数据与设置页分别展示地铁数据状态和铁路 PBF/graph 状态。地铁已就绪但铁路未安装时，地铁流程不能被阻塞。

## 10. GPX 规则

- 一个铁路 journey 对应一个 `<trk>`；连续铁路区间对应 `<trkseg>`，真正断开才分段。
- 铁路默认最大点间距 200 米，可选 100 米、500 米或原始折点；地铁默认仍为 25 米。
- 混合行程按 leg 模式分别加密，不能用全局 25 米把长距离铁路文件无意义放大。
- 默认不生成 `<time>`、速度或海拔。
- metadata 写入 OSM 署名、数据时间、图/Profile 版本和确认状态。
- coverage 去重第一版只保证同一铁路数据/图版本内稳定；跨版本几何差异必须提示，不静默合并。

## 11. 实施与验收顺序

### R0：长三角路径 POC

当前实现证据（2026-08-21）：

- OpenRailRouting 与 Geofabrik GraphHopper fork 已固定到提交，Maven 下载带 SHA-512 校验。
- Geofabrik Maven 仓库在当前网络不可访问时，构建脚本会从固定提交源码构建 fork，再构建 OpenRailRouting。
- `china_high_speed`、`china_emu`、`china_conventional` 三套 Profile 已通过夹具建图和 HTTP `/route` 验证，响应包含有效 WGS-84 几何与 `osm_way_id` 明细。
- graph cache 使用不可覆盖的版本目录，元数据记录 PBF SHA-256、OpenRailRouting/GraphHopper/Profile 版本和 ODbL 标识。
- sidecar 已验证只监听 `127.0.0.1`，FastAPI 在算路前校验 graph、PBF、Profile 和 OpenRailRouting commit 四元身份。
- 长三角真实图和四条固定线路已完成验证；全国图的八条跨区域样本也已通过路径、吸附、长度和响应时间门禁。

验证区间：

```text
上海虹桥 → 南京南
上海虹桥 → 杭州东
上海 → 苏州
上海虹桥 → 合肥南
```

PBF 准备、OpenRailRouting 建图、中国铁路 Profile、手动有序站点、候选地图和单条 GPX 已完成；真实铁路 GPX 也已由用户导入 Fog of World 并确认通过。

### R1：共享领域与单条行程

完成 Provider 接口、数据库迁移、铁路站点匹配、铁路录入模式、候选确认、不可变快照和单条 GPX 下载。

### R2：CSV 与行程管理

完成统一 CSV、逐站审核、铁路行程列表/编辑、混合模式导出和错误恢复。

### R3：全国数据与运维

完成全国图、版本并存、原子图切换、固定样本回归、磁盘/RAM 基准和月度更新流程。

全国验收基线：

- PBF：1,579,509,099 bytes；graph：186,698,828 bytes。
- 建图：165.55 秒；峰值 RSS 1,456,046,080 bytes。
- 图：645,361 nodes、742,281 edges；车站索引：18,490。
- 八条代表性路径验证中位延迟 16.014 ms，p95/最大值 17.127 ms。
- `active`/`previous` 使用安全相对 symlink 原子切换；验证报告身份不匹配时拒绝激活，并支持一次命令回滚。
- 图版本比较按 OSM 身份报告新增、移除、属性变化和受影响行程；显式重算必须重新人工确认，并创建新行程而不改写原快照。

### R4：可选授权时刻表

仅在数据源许可与版本机制通过审查后实施，不属于铁路首版完成条件。

铁路首版完成必须同时满足：真实区间地图人工核对、候选不静默消歧、预览/保存/GPX 几何哈希一致、GPX 1.1 XSD 通过、Fog of World 实机导入通过、OSM 署名可见、metro-only 模式无回归。上述门禁现均已有自动化、真实数据或用户实机证据；验收记录见 [`RAIL_FOG_ACCEPTANCE.md`](RAIL_FOG_ACCEPTANCE.md)。

## 12. 主要风险

- OSM 中国铁路标签和 `route=train` 关系不完整，不能当作时刻表真相。
- 省级提取的边界、枢纽多股道和平行高速/普速线可能产生错误候选。
- OpenRailRouting 图构建耗时并占用显著磁盘/RAM，必须先做区域基准再承诺全国配置。
- OSM/GraphHopper 版本更新会改变候选；历史行程必须依赖几何快照。
- ODbL 对公开分发衍生数据库有额外义务，不能把“代码开源”误当成“可直接分发全国图缓存”。

## 13. 官方参考

- [OpenRailRouting](https://github.com/geofabrik/OpenRailRouting)
- [Geofabrik 中国 OSM 下载](https://download.geofabrik.de/asia/china.html)
- [OpenStreetMap copyright 与 ODbL](https://www.openstreetmap.org/copyright)
- [OSMF Attribution Guidelines](https://osmfoundation.org/wiki/Licence/Attribution_Guidelines)
