# 平台支持与验证记录

[返回项目首页](../README.md)

以下为带日期的历史验证基线，不代表后续每个提交或安装包均已通过同一组验证。

## 2026-09-08：展示优化期间的复核

- 源码基线为 `5a31c2d5f15e72d3b018316efdcf3f12f546b7b5`；本次展示优化未修改应用代码。
- Windows 本地 `check`：后端 105/105、前端 10/10，通过 Ruff、Mypy、OpenAPI 漂移、ESLint 与生产构建；后端覆盖率 85.34%。
- 桌面/移动 Chromium E2E 20/20，真实 FastAPI + 临时 SQLite + 生产前端关键路径 1/1。
- [安装包工作流](https://github.com/Uddoo/transit2fog/actions/runs/34192998619)在 Windows x64、macOS arm64 均完成构建及隔离 smoke；Windows 产物下载后再次通过本机隔离 smoke。
- 3 个平台产物的 SHA-256 均通过下载后校验。正式签名、公证、扫描与人工发布审阅尚未完成，见[发行说明草稿](RELEASE_DRAFT.md)。
- 新拍摄地铁演示在独立数据库内通过预览、保存和下载 GPX；拍摄数据预处理、历史铁路截图的边界见[素材说明](MEDIA.md)。

## 已记录的平台基线

| 平台 | 原生入口 | 当前状态 |
|---|---|---|
| Windows 10/11 x64 | PowerShell 7：`.\transit2fog.ps1 <command>` | 核心应用与最小铁路 fixture 已完成实机验证；不依赖 WSL、Git Bash 或 GNU Make |
| macOS | Makefile：`make <target>` | 首个验收平台，继续保留 POSIX shell 工作流 |

2026-08-31 的 Windows 验证基线：核心 `check` 为 105 项后端测试、10 项前端测试、Ruff、Mypy、OpenAPI 漂移检查、ESLint 与生产构建全通过；后端覆盖率 85.33%，前端 statements/branches/functions/lines 为 66.01%/77.02%/60.64%/66.01%。桌面/移动 Chromium Mock E2E 为 20/20，另有 1 项真实 FastAPI + 临时 SQLite + 生产前端 E2E；约 124 MB 的完整 Windows 包也通过隔离迁移、地理库、API、安装和卸载 smoke test。铁路侧使用项目内 Temurin 21.0.12.1+1，OpenRailRouting 34/34 测试通过，Cologne fixture 路由为 13,706.7 米/172 点，当前与兼容 metadata 端点身份一致，验收退出后 8989/8990 均释放。

Cologne fixture 只用于验证 Windows JDK、构建、路由和进程清理链路，不是中国正式铁路图，也不会自动设为 `active`。实际录入铁路行程前仍需选择、构建并验证长三角或全国图。

带 production SPA、Alembic 和可选 sidecar JAR 的 Windows/macOS 安装包可由 `make package` 或 `.\transit2fog.ps1 package` 生成；tag 发布工作流会构建、隔离 smoke test 并上传带 SHA-256 的平台产物。详见[安装包文档](PACKAGING.md)。
