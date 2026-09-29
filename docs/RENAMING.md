# Transit2GPX 改名与升级

项目由 Transit2Fog 改名为 **Transit2GPX**，更早的名称为 Metro2Fog。新名称突出公共交通行程到标准 GPX 轨迹的转换，不限定用于世界迷雾。当前支持范围仍为地铁与铁路，本次改名不代表新增交通类型。

## 新名称

- 应用标题、API 标题、安装包和可执行文件：`Transit2GPX`。
- Windows 命令入口：`.\transit2gpx.ps1`；旧 `.\transit2fog.ps1` 保留为转发入口，参数继续传递。
- Python / npm 包：`transit2gpx-backend` / `transit2gpx-frontend`。
- 环境变量：`TRANSIT2GPX_*`。
- 新安装默认数据目录：平台对应的 `Transit2GPX` 应用数据目录；新数据库为 `transit2gpx.sqlite3`。
- GPX creator：`Transit2GPX`，下载文件名为 `transit2gpx_YYYY-MM-DD.gpx`；新备份格式为 `transit2gpx-backup-v1`。

## 已有数据与配置

无需为了改名搬移或重建已有数据库、备份、铁路图。

1. 同一配置项的变量名优先级为 `TRANSIT2GPX_*` → `TRANSIT2FOG_*` → `METRO2FOG_*`。
2. 未显式指定数据目录时，优先使用已存在的 `Transit2GPX` 目录，再查找 `Transit2Fog`、`Metro2Fog`；三者都不存在才创建新目录。
3. 未显式指定数据库 URL 时，在选定数据目录依次读取已存在的 `transit2gpx.sqlite3`、`transit2fog.sqlite3`、`metro2fog.sqlite3`。已有文件不会被自动改名或复制；多个目录或数据库并存时不会自动合并，可用 `TRANSIT2GPX_DATA_DIR` / `TRANSIT2GPX_DATABASE_URL` 明确选择。
4. 恢复脚本继续接受 Transit2Fog 与 Metro2Fog 的旧备份，仍验证文件集合、摘要和 SQLite 完整性。

铁路图元数据 `transit2fog-graph.json`（兼容 `metro2fog-graph.json`）、sidecar `/transit2fog/metadata` 接口及 Java 属性名保留原协议。GPX 铁路扩展命名空间 `https://transit2fog.local/gpx/rail/1` 和 `t2f-rail` 前缀保持不变，macOS bundle identifier 也保持稳定。这些是兼容标识，不是遗漏的产品名称。

## 仓库与历史素材

已有 `v1.0.0-rc.1` Release 属于改名前版本，附件和程序仍名为 Transit2Fog；本次源码改名不会更新已发布安装包，其发行说明保留原名称与构建证据。

本次修改源码和文档中的产品名称。GitHub 仓库、Git remote、工作区物理目录与 GitHub Social preview 设置没有自动改名；链接继续指向现有的 `Uddoo/transit2fog`，克隆示例显式使用 `transit2gpx` 作为本地目录名。

README 使用新标题的宽幅封面，旧封面保留。历史实机截图、录像、验收记录和已有决策仍保留当时的名称，不作为本次新版本运行证据。素材编辑提示词见 [MEDIA.md](MEDIA.md)。
