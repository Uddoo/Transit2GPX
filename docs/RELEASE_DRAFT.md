# v1.0.0-rc.1 发行说明

[下载预发布版](https://github.com/Uddoo/transit2fog/releases/tag/v1.0.0-rc.1)

这是 Transit2Fog 的首个安装包预发布版，包内应用版本为 1.0.0。产物尚未完成 Windows Authenticode、Apple Developer ID 签名、公证或恶意软件扫描；本次发布不代表已完成这些验证。

## 本版功能

- 将实际乘坐的中国地铁和铁路区间转为 GPX 1.1 轨迹，支持逐次行程与覆盖区间导出。
- 首次使用向导整合环境检查、数据导入、铁路服务启动与故障提示。
- 修复地图连续选站、行程分页与搜索、CSV 后台处理与中断恢复；优化列表查询和前端页面加载。
- 兼容历史数据库迁移 `20260928_0007`，自动补齐任务队列与铁路搜索结构，并保留已有行程和导入进度。

## 应该选择哪个文件

| 平台 | 文件 | 使用方式 |
|---|---|---|
| Windows 10/11 x64 | `Transit2Fog-1.0.0-windows-x64.zip` | 解压后直接运行 `Transit2Fog/Transit2Fog.exe`；也可用 PowerShell 7 运行包内 `install.ps1` |
| macOS Apple Silicon | `Transit2Fog-1.0.0-macos-arm64.pkg` | 系统安装程序包，当前未签名、公证 |
| macOS Apple Silicon 备用包 | `Transit2Fog-1.0.0-macos-arm64.tar.gz` | 同内容的 `.app` 归档，供手动部署 |

每个文件均有对应 `.sha256` 附件；以本次 Release 附件中的校验和为准，不要使用历史构建的摘要。本版不包含 Intel Mac 安装包。

## 首次启动后

1. 跟随首次使用向导检查环境并导入兼容的第三方地铁数据；详见[首次使用指南](GETTING_STARTED.md)。
2. 选择实际乘坐的城市、线路、起终点，预览并确认候选。
3. 保存后生成 GPX，先用少量行程在目标应用中抽检。

安装包自带 Python 运行库、生产前端、数据库迁移和铁路 sidecar JAR，无需安装 Python、Node.js、npm 或 uv。包内不含地铁数据、OSM PBF、铁路图或用户数据库；铁路仍需 Java 17+ 以及经过验证、激活的本地图。当前 Figshare 数据字段兼容限制见[数据获取步骤](GETTING_STARTED.md#2-获取一份地铁数据)。

## 构建与验证

- 构建日期：2026-09-28。
- 安装包源码提交：`d10322c6ac014320ffaea67d5d0456a1d330170e`。
- [标签构建与发布](https://github.com/Uddoo/transit2fog/actions/runs/36390973871)：Windows x64 与 macOS arm64，包含工作流内的隔离迁移、API 资源与地理库 smoke test；最终附件由此工作流生成并上传。
- [同一源码的发布预演](https://github.com/Uddoo/transit2fog/actions/runs/36388958848)：两平台包通过 SHA-256 与资源核对；macOS 预演包在外部 Python / Node.js 不可用时，通过首次向导、地铁导入、行程保存、GPX 导出、铁路测试图服务和旧数据库迁移验证。
- [源码 CI](https://github.com/Uddoo/transit2fog/actions/runs/36388647207)：macOS / Windows、Python 3.11 / 3.13 质量检查及两平台浏览器测试通过。
- 本地后端 125 项测试通过，覆盖率 86.95%；历史数据库迁移前后的原有表内容核对一致。

本次自动验证不替代签名、公证、恶意软件扫描、各平台的人工安装验收或中国铁路全国图在 Windows 上的资源验收。完整边界见[已知限制](KNOWN_LIMITATIONS.md)。
