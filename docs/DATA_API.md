# 数据与 API 契约

## 1. 数据源策略

v1.0 的规范数据源是 CPTOND-2025。导入器以线路和站点数据重建带 route variant 语义的站间 edge；发布的 segments 只用于交叉校验和显式兜底，因为它不应被假定始终保留稳定的线路、方向和支线语义。

实际文件名、字段名和打包层级必须由 importer adapter 处理，并通过真实 v2 数据审计固定下来，不能把研究对话中的示例路径写死为唯一格式。

所有原始记录保留来源标识。许可、来源 URL、数据版本和校验和展示在“数据与设置”页面并进入导出元数据。

## 2. 坐标约定

| 边界 | 坐标顺序/基准 |
|---|---|
| 数据库存储 | WGS‑84，WKB 使用 `x=lon, y=lat` |
| Shapely | `Point(lon, lat)` |
| GeoJSON | `[lon, lat]` |
| Leaflet | `[lat, lon]`，只在地图适配层转换 |
| GPX | `lat="..." lon="..."` |
| 距离/切割 | 局部 AEQD 米制 CRS |

禁止在 EPSG:4326 上把欧氏长度当作米，也禁止在通用领域对象里使用无标签的二元坐标数组。

## 3. 核心数据库模型

以下字段是逻辑契约，具体 SQL 类型、索引和约束由 Alembic 迁移定义。

### 3.1 数据集与网络

```text
dataset_version
  id, source_name, source_version, captured_at, license,
  source_url, checksum, imported_at, completed_at, importer_schema_version,
  route_count, stop_count, total_cities, processed_cities,
  ready_lines, blocked_lines, error_code, error_message, status

city
  id, dataset_version_id, source_city_code, name_cn, name_en,
  center_lon, center_lat, min_lon, min_lat, max_lon, max_lat, status

line
  id, city_id, name_cn, name_en, normalized_name,
  display_color, sort_order, status

route_variant
  id, line_id, dataset_version_id, source_route_id, source_route_name,
  direction_name, is_loop, is_branch, geometry_wkb,
  match_method, quality_status, quality_flags_json

station
  id, city_id, name_cn, name_en, normalized_name,
  pinyin_full, pinyin_initials, lon, lat, cluster_no

station_alias
  id, station_id, alias, normalized_alias, language, source

route_stop
  id, route_variant_id, station_id, source_stop_id, source_sequence,
  source_lon, source_lat, projected_measure_m, projection_error_m,
  match_quality

route_edge
  id, route_variant_id, from_route_stop_id, to_route_stop_id,
  from_station_id, to_station_id, sequence_from, sequence_to,
  distance_m, geometry_wkb, min_lon, min_lat, max_lon, max_lat,
  quality_status, quality_flags_json
```

关键约束：

- `line.normalized_name` 在同一 city 内唯一。
- `route_stop` 在 route variant 内按 source sequence 唯一或有显式冲突记录。
- `route_edge` 的 from/to stop 必须属于同一 route variant。
- 可导出 edge 的 `quality_status = ready`。
- FTS5 索引站点中文、英文、拼音和别名；RTree 索引站点和 edge bbox。

### 3.2 行程

```text
journey
  id, journey_code, traveled_at, source_type, note, created_at, updated_at

journey_leg
  id, journey_id, leg_no, dataset_version_id, city_id, line_id,
  route_variant_id, start_station_id, end_station_id, direction,
  resolution_status, resolution_message, candidate_digest

journey_leg_edge
  journey_leg_id, route_edge_id, order_no, reversed
```

`journey_leg_edge` 是预览与导出的事实来源。唯一约束是 `(journey_leg_id, order_no)`；同一 leg 不得重复同一顺序。

### 3.3 CSV 审核

```text
import_batch
  id, filename, encoding, total_rows, resolved_rows, review_rows,
  failed_rows, status, created_at, committed_at

import_row
  id, batch_id, row_no, raw_json, normalized_json,
  resolution_status, matched_city_id, matched_line_id,
  matched_start_station_id, matched_end_station_id,
  selected_candidate_id, candidate_json, error_code, error_message
```

状态：

- batch：`parsing | ready_for_review | committing | committed | failed | cancelled`
- row：`resolved | needs_review | unresolved | ignored | committed`
- leg：`resolved | needs_review | invalidated`

## 4. CSV 契约

```csv
journey_id,leg_no,city,line,start_station,end_station,traveled_at,direction,via_station,note
20260820-01,1,上海,2号线,虹桥火车站,人民广场,2026-08-20,,,
20260820-01,2,上海,1号线,人民广场,徐家汇,2026-08-20,,,
20250501-01,1,北京,10号线,国贸,巴沟,2025-05-01,内环,,
```

| 字段 | v1.0 | 规则 |
|---|---|---|
| `journey_id` | 可选 | 相同值的连续/有序行组成一次行程；缺省时每行一程 |
| `leg_no` | 可选 | 同 journey 内正整数且不重复；缺省按文件顺序 |
| `city` | 必填 | 可接受“市”后缀并规范化 |
| `line` | 必填 | 首版不自动提交无线路输入 |
| `start_station` | 必填 | 必须与终点不同 |
| `end_station` | 必填 | 必须与起点不同 |
| `traveled_at` | 可选 | ISO `YYYY-MM-DD` |
| `direction` | 可选 | 内环、外环、顺时针、逆时针或数据源方向别名 |
| `via_station` | 可选 | 多站以 `|` 分隔并按乘坐顺序解释 |
| `note` | 可选 | 长度受限的纯文本 |

编码只接受 UTF-8 与 UTF-8-SIG。未知列可保留在 `raw_json` 但给出警告；缺少必填列是 batch 级错误。公式单元格按文本处理，导出 CSV 时需要防止表格公式注入。

## 5. REST API

所有接口位于 `/api/v1`，返回 JSON 的错误统一为：

```json
{
  "error": {
    "code": "path_ambiguous",
    "message": "找到多个可能的乘坐方向",
    "details": {},
    "request_id": "req_..."
  }
}
```

### 5.1 健康与数据

```http
GET  /healthz
GET  /api/v1/data/status
POST /api/v1/data/imports
GET  /api/v1/data/imports/{import_id}
POST /api/v1/data/imports/{import_id}/cancel
GET  /api/v1/data/quality
```

`POST /data/imports` 接受服务端可读目录配置或受限上传包；耗时处理返回 `202` 和可轮询的 import ID。
`GET /data/status` 同时返回当前任务 ID、城市级进度、可用/阻断线路计数、来源、checksum、adapter 版本及失败原因。staging 数据按城市提交以便观察和取消，但只有全部质量检查完成后才会原子切换为 active；旧 ready 数据在此期间继续可用。

### 5.2 城市、线路、站点与地图

```http
GET /api/v1/cities
GET /api/v1/cities/{city_id}/lines
GET /api/v1/cities/{city_id}/stations
GET /api/v1/lines/{line_id}/stations
GET /api/v1/stations/search?city_id=...&line_id=...&q=...
GET /api/v1/cities/{city_id}/map?line_id=...&bbox=...
```

地图接口返回 bbox 与线路/站点 FeatureCollection。总览可使用单独保存的简化几何；路径候选与导出只能使用完整 edge 几何。

地图 GeoJSON 仅来自已经通过质量门禁的本地数据版本。前端不得为未就绪、空结果或失败响应生成示意线路；这三类状态分别显示真实底图与状态说明。GeoJSON 坐标始终是 `[lon, lat]`，只在 Leaflet 边界转换为 `[lat, lon]`。

地图供应商为运行时公开配置：

```http
GET /api/v1/config/public
```

响应包含 `map.tiles_enabled`、`tile_url`、`tile_attribution`、`max_zoom` 与 `external_tiles`。瓦片 URL 不写死在前端构建中；关闭外部瓦片后，CPTOND 线路层仍可在无底图画布上使用。

### 5.3 路径候选

```http
POST /api/v1/paths/preview
```

请求：

```json
{
  "city_id": 1,
  "line_id": 12,
  "start_station_id": 101,
  "end_station_id": 132,
  "direction": "auto",
  "via_station_ids": []
}
```

响应：

```json
{
  "status": "resolved",
  "candidates": [
    {
      "candidate_id": "cand_opaque",
      "digest": "sha256:...",
      "dataset_version_id": 2,
      "route_variant_id": 18,
      "line_name": "2号线",
      "direction_name": "上行",
      "distance_m": 18342.7,
      "station_count": 13,
      "station_ids": [101, 102, 103, 132],
      "edge_ids": [501, 502, 503],
      "reversed_edges": [false, false, false],
      "geometry": {"type": "LineString", "coordinates": []},
      "warnings": [],
      "legs": []
    }
  ]
}
```

`status` 可为 `resolved | needs_review | unresolved`。即使只有一个候选，只要含阻断性质量 flag 也不能返回 `resolved`。

`line_id=null` 表示自动规划换乘。服务端使用 `(station_id, line_id)` 状态图返回最多五个候选，并固定返回 `needs_review`；每个候选的 `legs` 包含可独立校验和保存的线路分段。当前自动换乘模式不接受 `via_station_ids`，需先指定线路才能使用途经站过滤。

### 5.4 行程

```http
GET    /api/v1/journeys
POST   /api/v1/journeys
GET    /api/v1/journeys/{journey_id}
PATCH  /api/v1/journeys/{journey_id}
DELETE /api/v1/journeys/{journey_id}
POST   /api/v1/journeys/{journey_id}/re-resolve
```

创建行程提交 candidate ID、digest 和用户输入。服务端重新校验候选仍属于当前数据版本且 edge 列表未变化，再在一个事务中写入 journey、legs 和 edges。
元数据更新可提交 `expected_updated_at`；若行程已被另一操作修改，返回 `409 journey_update_conflict`，不会覆盖较新的内容。

### 5.5 CSV 导入

```http
POST   /api/v1/import-batches
GET    /api/v1/import-batches/{batch_id}
GET    /api/v1/import-batches/{batch_id}/rows
PATCH  /api/v1/import-batches/{batch_id}/rows/{row_id}
POST   /api/v1/import-batches/{batch_id}/resolve
POST   /api/v1/import-batches/{batch_id}/commit
DELETE /api/v1/import-batches/{batch_id}
```

分页查询 rows。修改输入或候选后重新计算统计。`commit` 对已解析行全事务提交，对未处理的 review/unresolved 行返回阻止原因，不进行部分静默提交；若产品允许“只提交 resolved”，必须由用户显式选择。

### 5.6 导出

```http
POST /api/v1/exports/preview
POST /api/v1/exports/gpx
```

请求过滤条件包括 journey IDs、城市、线路、日期范围；选项包括 `mode=journeys|coverage` 和 `max_segment_length_m=15|25|50|null`。

预览返回行程数、edge 数、去重数、总距离、轨迹/segment 数、数据版本集合、阻断错误和警告。只有相同请求的预览摘要仍有效时才生成下载。

## 6. GPX 契约

- 根元素为 GPX 1.1 命名空间，`creator="Metro2Fog"`。
- 普通模式：每个 journey 一个 `trk`，每个 leg 一个 `trkseg`。
- 覆盖模式：相同 edge 只出现一次；只把端点一致且拓扑连续的 edge 放入同一 `trkseg`。
- 坐标保留足够精度（建议 7 位小数），相邻重复点去重。
- 加密在米制 CRS 中完成，再转回 WGS‑84。
- 默认不含 `<time>`、虚构海拔或速度。
- 生成后依次执行 XSD、坐标范围、每段至少两个不同点和跳跃距离检查。
- 响应使用安全文件名，例如 `metro2fog_2026-08-20.gpx`。

## 7. 数据版本与迁移

- 数据集导入和数据库 schema 迁移是两套独立版本。
- 原始输入 checksum 或 importer 算法变化会创建新 `dataset_version`。
- 旧行程保持可导出，只要引用的旧 edge 仍保留且质量未被撤销。
- “迁移到新数据”先生成差异报告，用户确认后创建新的 leg-edge 关系；不原地覆盖。
