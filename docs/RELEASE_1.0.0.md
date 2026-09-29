# Transit2GPX v1.0.0

[下载正式版](https://github.com/Uddoo/Transit2GPX/releases/tag/v1.0.0)

把实际乘坐的地铁与铁路区间转成标准 GPX 轨迹。该版本正式采用 Transit2GPX 名称，延续 Transit2Fog / Metro2Fog 的本地数据与配置兼容。

## 本版内容

- 地铁和铁路候选路径预览、用户确认、行程保存，以及逐次行程/区间去重 GPX 导出。
- 首次使用向导、标准城市数据包、城市选择与显式起终点选择。
- 行程分页检索、CSV 后台处理、刷新后的任务恢复和旧数据库迁移兼容。
- 轻量桌面主包；铁路 JAR 与 Temurin 21 JRE 按需下载、校验与复用，不改系统 Java 或 PATH。
- 新版真实界面截图和中文使用文档。

## 下载选择

| 平台 | 文件 | 使用方式 |
|---|---|---|
| Windows 10/11 x64 | `Transit2GPX-1.0.0-windows-x64-Setup.exe` | 双击安装，不要求管理员权限或 PowerShell |
| Windows 10/11 x64 | `Transit2GPX-1.0.0-windows-x64.zip` | 解压后运行 `Transit2GPX/Transit2GPX.exe` |
| macOS Apple Silicon | `Transit2GPX-1.0.0-macos-arm64.pkg` | 系统安装程序包 |
| macOS Apple Silicon | `Transit2GPX-1.0.0-macos-arm64.tar.gz` | 同内容的应用归档 |

每个主包和铁路组件 ZIP 均提供对应 `.sha256` 校验文件。普通用户从主包开始，铁路组件由应用在需要时下载。当前不提供 Intel Mac 安装包。

## 数据与升级

主包无需 Python、Node.js、npm 或 uv，不包含全国地铁/铁路原始数据和个人数据库。城市数据可在向导中按需选择；铁路组件就绪后仍需准备与激活经过验证的 PBF/graph。原始 Shapefile 导入需要源码环境或自行构建的完整导入版。

既有数据库、行程和备份无需为改名重新创建；同名配置优先读取 `TRANSIT2GPX_*`，再兼容 `TRANSIT2FOG_*` 和 `METRO2FOG_*`。升级前建议保留备份，完整说明见[改名迁移说明](RENAMING.md)。

## 验证与限制

Release 页面记录最终源码 SHA、构建运行与附件摘要。流水线包含双平台质量与浏览器检查，构建包含隔离数据库迁移、API 路由、资源和地理运行库 smoke test；这些不等同于所有目标设备的人工安装验收。

本版未做 Windows Authenticode、Apple Developer ID 签名或 macOS 公证；不宣称通过完整恶意软件扫描。系统可能显示未知发布者提示。请核对来源和 SHA-256，不要关闭系统安全防护。正式版标记不表示已经完成签名、公证。

底图需要联网。数据为固定快照，不能保证实时运营变化；铁路候选需要本人确认。历史 Fog of World 实机验收仍是历史证据，本版未重新执行外部设备验收。详见[已知限制](KNOWN_LIMITATIONS.md)。
