# 标准城市数据包与轻量运行库

此功能在轻量打包分支实现，尚未改变已发布的 v1.0.0-rc.1 附件。

## 用户使用

首次使用向导和“数据与设置”均可选择 `.t2fcity` 文件。文件无需解压，也无需填写路径。应用先显示城市、来源版本、数据时间、许可、署名和质量检查数量；点击“安装城市数据”后才写入线路数据库。安装完成后可选站、预览、保存行程并导出 GPX。

每份包只含一座城市。允许同时安装多个城市；更新某个城市不会替换其他城市。旧线路数据保留供历史行程引用，默认选站入口使用该城市最新的可用版本。重复安装同一份包复用已有线路，不复制站点。

安装使用单个数据库事务，异常时整体回滚。城市包缓存保存在应用数据目录 `city-packs/`，来源清单另存入数据库，卸载程序不会删除这些数据。

独立数据预发布版 [metro-data-2025-06-r1](https://github.com/Uddoo/transit2fog/releases/tag/metro-data-2025-06-r1) 已提供 46 个上游城市条目、城市包和 `catalog.json`。本阶段客户端仍通过本地文件选择导入；应用内目录接入属于后续 UI 修复。工具生成的 `index.json` 不会自动上传，也不表示数据获得了再分发许可。数据快照为 2025 年 6 月，不能当作最新线路快照；已发布程序 v1.0.0-rc.1 不支持城市包格式。

## 格式 v1

`.t2fcity` 是 ZIP 容器，只允许两个文件，不执行 SQL、Python 或 pickle，也不把文件解压到用户指定路径：

| 文件 | 内容 |
|---|---|
| `manifest.json` | `format=transit2fog-city-v1`、城市编码和名称、网络文件 SHA-256、完整来源与署名 |
| `network.json` | `cities`、`stations`、`lines`、`variants`、`stops`、`edges`、`aliases` 七组规范化记录 |

来源字段包含原始数据名、版本、URL、许可、采集时间、原始 checksum、导入器版本及署名。不会把城市包的校验和冒充原始数据的校验和。重新导出已安装包时保留原始来源。

网络记录沿用应用的规范化字段；数据库主键在包内只是局部编号。导入时重新分配编号并重写所有外键，不使用包内编号覆盖现有记录。几何为 WGS84 二维 WKB 的十六进制字符串。根城市/数据集外键由安装器分配，包不得指定；具体字段由 `app/importers/city_pack.py` 的固定表集合和字段验证约束。格式变动需要新的格式版本。

默认限制：压缩包不超过 32 MiB，网络 JSON 不超过 128 MiB，清单不超过 64 KB，各表最多 100,000 条记录。导入会检查字段类型、有限数值、坐标范围、几何、重复局部编号、跨表引用、片段站序、包围盒与可用线路完整性。原始质量阻断记录保留，不能因打包而变为可用线路。数据库的唯一性和外键约束继续生效。

SHA-256 检测文件损坏和预览后的变化，不证明数据来源真实或时效性；用户仍应核对来源和许可。

## 生成城市包

从已通过质量门禁的本地数据库导出；源库通过 SQLite `mode=ro` 打开，只查询地铁网络表，不复制行程、用户设置或铁路历史：

```powershell
uv run --project backend python scripts/build_city_packs.py `
  --database C:\Data\validated.sqlite3 `
  --city-code 021 `
  --output release\city-packs `
  --attribution "填写原始数据作者、许可和来源链接"
```

`--city-code` 可重复传入；省略时导出所有当前可用城市。文件名使用城市编码摘要，避免平台路径差异，真实城市名保存在清单中。`index.json` 同时记录包的 SHA-256、文件大小和预览信息。

从原始 Shapefile 制包，重型处理只在隔离临时数据库中进行：

```powershell
uv run --project backend --group import-tools python scripts/build_city_packs.py `
  --raw-directory C:\Data\CPTOND `
  --source-version CPTOND-local-snapshot `
  --output release\city-packs `
  --attribution "填写原始数据作者、许可和来源链接"
```

保留原始字段适配、CRS 检查、站序重建、环线/支线处理和质量门禁。提供不兼容原始数据仍会失败，不会通过标准包掩盖原始数据缺陷。

## 依赖与分发边界

基础依赖不再包含 GeoPandas、Pandas、Pyogrio/GDAL；它们移至 `import-tools` 依赖组，开发组仍包含它以运行完整回归测试。Shapely、NumPy、PyProj 继续用于运行时几何和 GPX，不做不安全的 DLL 去重。

默认 PyInstaller 构建排除这些重型包和原始 CPTOND 导入器。基础版的原始 Shapefile API 返回明确的 `raw_import_unavailable`，UI 引导选择标准包。完整导入版可通过 `--with-import-tools` 构建，应使用独立输出目录：

```powershell
uv run --project backend python scripts/build_package.py `
  --with-import-tools --output release\import-tools-edition
```

铁路 PBF 站点读取改为 Pyosmium，支持节点、闭合面和带成员几何的关系，继续保留中文名、别名、站码和城际/地铁排除规则。GDAL 读取路径保留为完整环境中的兼容适配器及对照测试。基础版不因拆除 GDAL 而要求用户自行转换铁路站点。

Windows 从旧包升级时只清理程序 `_internal` 下已移除的 Pandas/Pyogrio 库目录，保留独立应用数据；完整导入版保留这些库目录。两种版本共用数据模型。
