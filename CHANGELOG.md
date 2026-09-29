# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/)。

## [1.0.1] - 2026-09-29

- 为本地服务增加 Host、Origin 和 Fetch Metadata 校验，拒绝外站与 DNS rebinding 请求，保留同源和本地 CLI 访问。
- 将铁路 HSTORE 标签解析改为线性扫描，修复畸形反斜杠输入导致的正则回溯风险。
- 铁路验收脚本限制 loopback 端点、禁用环境代理与自动重定向，保留旧 metadata 回退。
- 加固铁路图激活与回滚的版本名和目录边界校验。
- 固定 GitHub Actions 完整提交 SHA，记录 19 条 CodeQL 告警的逐条审阅依据。
- 保留既有数据、备份与显式本地 Java/目录配置兼容；不移动或替换 v1.0.0 产物。

## [1.0.0] - 2026-09-29

- 项目改名为 Transit2GPX，同步应用、包名、命令入口、安装产物和 GPX 导出名称。
- 保留 Transit2Fog / Metro2Fog 配置、数据库、备份和既有铁路协议兼容；详见 [改名迁移说明](docs/RENAMING.md)。

- 正式提供 Windows x64 安装器与便携包、macOS Apple Silicon 安装包。
- 轻量主包支持标准城市数据包，铁路 JAR/JRE 按需下载并验证摘要。
- 新增城市数据选择、首次使用向导、显式选站、分页检索与 CSV 后台恢复。
- 更新新版真实截图；既有行程、配置与备份兼容保留。

### v1.0 功能基础（2026-08-31）

- 完成 CPTOND 地铁数据导入、路径候选、行程管理、CSV 审核与 GPX 1.1 导出。
- 完成中国铁路 R0–R3：固定 OpenRailRouting sidecar、车站索引、候选确认、不可变快照和混合 GPX。
- 完成 Windows 10/11 x64 PowerShell 7 与 macOS 原生运行入口。
- 完成桌面与移动 Chromium 核心流程验收，以及地铁和铁路 GPX 的兼容应用实机抽检。
- 增加真实 FastAPI、临时 SQLite 与生产前端组成的全栈 Playwright 行程/GPX 验收。
- 增加 OpenAPI TypeScript 类型生成与漂移检查，并启用前后端覆盖率门禁。
- 增加 Windows/macOS、Python 3.11/3.13 的跨平台 CI 质量矩阵。
- 增加行程服务端分页与固定批量查询，消除列表响应随行程数增长的 N+1 查询。
- 将铁路站名接入独立 FTS5 索引，并让地图视口查询实际使用站点与线路 edge RTree。
- 增加 SQLite 持久化任务执行器，支持 CPTOND/铁路导入任务在服务重启后恢复。
- 拆分查询、空间和导入任务服务层，并以 `scripts/project.py` 统一 Make、PowerShell 与 shell 核心命令。
- 将五个前端业务路由改为懒加载，使用 Vite manifest 检查独立 chunk，并把主入口从约 505 kB 降至约 281 kB。
- 增加 Windows/macOS PyInstaller 安装产物、隔离 smoke test、SHA-256 与 tag 发布工作流；可选内置固定 sidecar JAR 及第三方声明。
- 增加 OpenRailRouting sidecar supervisor，实现单命令启动、graph/PBF/commit 身份验证、既有进程复用、日志和自有进程回收。
- 安装包 smoke test 现在会验证 Alembic、API 路由、PyProj/Shapely/PyOgrio 运行资源，并修复站点组合框延迟查询期间可能选择旧候选的竞态。
