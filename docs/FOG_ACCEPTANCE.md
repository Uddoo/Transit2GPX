# Fog of World 实机验收

最后更新：2026-08-21。

## 目的

这是原 Metro2Fog v1.0（现 Transit2Fog）在第三方应用中的外部兼容验收记录。Fog of World 官方页面当前明确支持导入 GPX/KML，并声明同时支持 WGS-84 与中国 GCJ-02。Transit2Fog 输出 WGS-84 GPX 1.1，不在导出时擅自转换为 GCJ-02。该验收已于 2026-08-21 由用户确认通过。

- 官方功能说明：<https://fogofworld.app/zh-hans/>
- 官方隐私与云端导入目录说明：<https://fogofworld.app/en/privacy_policy>

## 验收文件

文件位于被 `.gitignore` 排除的本机目录 `data/validation-exports/`：

| 文件 | 预期结构 | SHA-256 |
|---|---|---|
| `sciencedb-dongguan-shanghai-journeys.gpx` | 2 tracks、2 segments、2,367 points | `af4de81a82578763e75ef9f01a37860a43e33fe3afb8bed61c86cda58191d6d0` |
| `sciencedb-dongguan-shanghai-coverage.gpx` | 1 track、2 segments、2,367 points | `a63ca16295534d9ce0e658354a10742ce573d0df6aef785dd769dfb9949c6692` |

两份文件覆盖同一组 27 条真实 route edge、总长 54,580.90 m：

- 东莞轨道交通 2 号线反向样例，14 edge、36,915.27 m。
- 上海地铁 4 号线内圈的一条已确认候选，13 edge、17,665.63 m。

应用内 GPX 1.1 XSD、坐标范围、点间距、跳跃距离和确定性校验已通过。独立 GDAL GPX 驱动也能把 journey 文件读取为 2 个 `MultiLineString`，把 coverage 文件读取为 1 个 `MultiLineString`，两者均为 EPSG:4326、2,367 个 `track_points`。

## 安全准备

1. 记录 Fog of World 平台与版本号。
2. 在 Fog of World 中新建临时数据库；若当前版本没有该入口，则先创建快照或完整备份。不要直接拿唯一的正式数据库试验。
3. 把两份 GPX 传到该设备可访问的本地文件或 Fog of World 支持的个人云存储位置。
4. 先只导入 journey 文件；coverage 文件应在恢复快照或另一临时数据库后测试，避免同一路段重复写入影响观察。

## 验收步骤

### 1. Journey 模式

1. 在 Fog of World 中选择导入轨迹并打开 `sciencedb-dongguan-shanghai-journeys.gpx`。
2. 确认应用没有报告 XML、GPX、坐标或空轨迹错误。
3. 定位东莞，确认轨迹位于东莞火车站至虎门火车站的轨道交通 2 号线走廊。
4. 定位上海，确认轨迹位于地铁 4 号线内圈走廊。
5. 确认应用把它们作为两条轨迹处理，没有用一条跨城直线连接东莞与上海。

### 2. Coverage 模式

1. 恢复导入前快照，或切换到另一临时数据库。
2. 导入 `sciencedb-dongguan-shanghai-coverage.gpx`。
3. 确认应用没有报错，并同时显示东莞与上海轨迹。
4. 确认两个 `trkseg` 保持断开；两座城市之间不得出现穿越中国的直线。
5. 放大两座城市，确认路线没有系统性的整体偏移。

## 通过标准

只有以下条件全部成立，才能关闭 v1.0 的 Fog of World 外部验收项：

- 两份 GPX 均能导入，无格式或坐标错误。
- 东莞和上海轨迹出现在正确城市及地铁走廊附近。
- journey 的两个 tracks 没有被错误连接。
- coverage 的两个 segments 没有被错误连接。
- WGS-84 轨迹没有明显的中国地图坐标偏移。
- 测试数据库、快照或备份能够恢复，未污染用户唯一的正式数据库。

## 结果记录

### 已完成结果

- 验收日期：2026-08-21。
- 结果：V1.0 GPX 手动导入 Fog of World 通过。
- 证据来源：用户在当前 Transit2Fog 完成任务中明确反馈实机验证通过，并确认 goal 可标记为完成。
- 结论：关闭 v1.0 的 Fog of World 外部验收项。

后续数据版本或 Fog of World 版本升级时，可继续使用下方模板执行回归抽检：

完成后在下方记录，或把同样信息回复给当前 Codex 任务：

```text
平台：iOS / Android
Fog of World 版本：
Journey 导入：通过 / 失败
Coverage 导入：通过 / 失败
东莞位置：通过 / 失败
上海位置：通过 / 失败
跨城错误连线：无 / 有
坐标整体偏移：无 / 有
快照或测试数据库恢复：通过 / 失败
错误信息或备注：
```
