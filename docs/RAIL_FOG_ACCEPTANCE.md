# Fog of World 铁路实机验收

状态：通过。用户已在实际安装的 Fog of World 中手动导入铁路 GPX。最后更新：2026-08-21。

## 验收文件

首个全国铁路验收文件由北京南到上海虹桥的已确认铁路快照生成：

```text
data/rail-national-acceptance/beijing-south-shanghai-hongqiao.gpx
```

固定证据：

- 文件大小：395,879 bytes。
- SHA-256：`5c042836b17e3e4cdc0b82087fcde4a8a9b2da95c742c2b9b3b8a2fbd1690ecd`。
- GPX 1.1，WGS-84，共 7,894 个 `trkpt`，无伪造时间和海拔。
- 铁路图：`china-20260815-r3.1`。
- Profile：`2026-08-21-r0.1`。
- candidate digest：`sha256:5eff3b41db434078de3fd0c3b91e28dfb8d405188455839b0c527d8552d5f888`。
- source geometry SHA-256：`b20149cee3dde48ddcabc8c617b69c9b4d320e30cccfb29fb50a8f07aa87aa8f`。
- metadata 包含 `© OpenStreetMap contributors` 和 OSM copyright 链接。

该文件已经通过 XML/GPX XSD、坐标范围、轨迹段和几何连续性自动检查。

## 实机步骤

1. 在 Finder 中定位上述 GPX；如文件经复制或传输，先重新计算 SHA-256 并与本页核对。
2. 打开 Fog of World，使用其“导入轨迹/GPX”入口选择该文件。
3. 等待导入完成，不要在处理中重复选择同一文件。
4. 在北京南、济南西、南京南、上海虹桥等位置抽查轨迹，确认沿铁路走廊连续显示，没有跨城市直线、道路绕行或大范围跳点。
5. 记录导入是否成功、Fog of World 版本、设备/系统、导入日期和异常截图。

## 通过标准

- 应用接受文件且不报告格式错误。
- 北京到上海形成一条连续铁路轨迹；没有连接起终点的直线替代路径。
- 抽查节点落在预期铁路走廊，轨迹没有明显省界断裂。
- 导入没有生成虚假时间线、高程或速度信息。
- 若重复导入行为由 Fog of World 自身决定，只记录结果，不据此修改 Transit2Fog 几何。

## 结果记录

```text
结果：通过
验收日期：2026-08-21
Fog of World 版本：用户未记录
设备与系统：用户未记录
SHA-256 已核对：未单独记录
连续铁路轨迹：导入成功，用户确认通过
明显直线或跳点：用户未报告
备注：用户在当前任务中明确反馈“手动测试生成铁路 gpx 并导入世界迷雾成功”。
```

结论：铁路首版最后一个外部门槛关闭，Transit2Fog 名称迁移可以发布。后续铁路数据或 Fog of World 版本升级时应重新抽检。
