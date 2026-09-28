# v1.0.0 发行说明草稿

状态：**待发布检查完成，尚未正式发布。** 本文是已构建产物的说明草稿，不是下载已开放的声明。

## 这是什么

Transit2Fog 把实际乘坐的中国地铁和铁路区间转成 GPX 轨迹。选择起终点、预览候选并确认后，即可导出给世界迷雾等支持 GPX 1.1 轨迹的应用。

## 应该选择哪个文件

| 平台 | 文件 | 使用方式 |
|---|---|---|
| Windows 10/11 x64 | `Transit2Fog-1.0.0-windows-x64.zip` | 解压后用 PowerShell 7 运行包内 `Transit2Fog/install.ps1`，或直接运行包内程序 |
| macOS Apple Silicon | `Transit2Fog-1.0.0-macos-arm64.pkg` | 完成正式签名与公证后，使用系统安装程序安装 |
| macOS Apple Silicon 备用包 | `Transit2Fog-1.0.0-macos-arm64.tar.gz` | 同内容的压缩归档，供手动部署 |

本次工作流未生成 Intel Mac 安装包，不应将 arm64 包标为通用 macOS 包。

## 首次启动后

1. 先准备并导入兼容的第三方地铁数据；详见[首次使用指南](GETTING_STARTED.md)。
2. 选择自己实际乘坐的城市、线路和起终点，预览并确认候选。
3. 保存后生成 GPX，先用少量行程在目标应用中抽检。

安装包包含应用和生产前端，不包含地铁数据、OSM PBF、铁路图或用户数据库。铁路还需 Java 17+ 以及经过验证、激活的本地图；包内 sidecar JAR 不能替代这些准备步骤。

## 本次构建与验证

- 构建日期：2026-09-08。
- 源码提交：`5a31c2d5f15e72d3b018316efdcf3f12f546b7b5`。
- [GitHub Actions 构建 #34192998619](https://github.com/Uddoo/transit2fog/actions/runs/34192998619)：Windows x64 与 macOS arm64 均通过构建及工作流内隔离 smoke test；通过 `workflow_dispatch` 触发，发布步骤未执行。
- 下载产物后，3 个文件的 SHA-256 均与工作流提供的校验文件一致。
- Windows ZIP 在本机解压后再次通过独立运行目录中的迁移、资源、API 与地理库 smoke test。
- Windows ZIP 包含 LICENSE、NOTICE、ATTRIBUTION、安装/卸载脚本；未发现用户数据库、OSM PBF 或 `.env` 文件。
- 同一源码的本地 `check` 通过：后端 105 项、前端 10 项，后端覆盖率 85.34%，以及类型、风格、API 契约和生产构建检查。
- 本地 E2E：桌面/移动 Chromium 20/20、真实 FastAPI + SQLite + 生产前端保存导出路径 1/1。

本次验证不包含 macOS 桌面安装后的人工操作、签名、公证、杀毒扫描或中国铁路全国图的本机运行。

## 当前构建的 SHA-256

```text
9bd4a84bcb7d6d91104859d39641bf42f43ca914c2fde318deff63ad00993143  Transit2Fog-1.0.0-windows-x64.zip
bb6a6ca255cd21038efd96757e61ce9fb4957d91a32514fa24d068e4059c479c  Transit2Fog-1.0.0-macos-arm64.pkg
4c904487053a3d3c337425f566d953fef48d3a0e238ba5d782fc7b2caf9bf659  Transit2Fog-1.0.0-macos-arm64.tar.gz
```

以上只适用于此次未签名构建。签名、公证或重新打包后必须重新计算并替换校验和。

## 正式发布前剩余事项

- 按[安装包文档](PACKAGING.md)完成 Windows Authenticode、Apple Developer ID 签名/公证及恶意软件扫描。
- 重新生成并审阅依赖许可快照；按[安装包文档](PACKAGING.md)核对分发要求，并完成人工安装验证与发布审阅。
- 核对目标 tag、最终源码提交、平台安装体验与最终签名产物摘要。
- 明确当前 Figshare 原始包的字段兼容限制；不能宣传为“下载即用”或“自带全国数据”。

GitHub Actions artifact 有保留期限，不替代正式 Release 附件。本次下载的产物保存在被忽略的本机工作目录；完成发布条件后才应将最终制品附加到正式 Release。
