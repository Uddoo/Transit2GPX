# Transit2GPX v1.0.1

本版是 v1.0.0 的安全加固更新，建议升级。既有行程、数据库、备份以及 Transit2Fog / Metro2Fog 配置兼容继续保留。

## 本版修复

- 本地 API 增加 Host、Origin 和 Fetch Metadata 检查，防止外站与 DNS rebinding 请求访问本机数据操作；同源页面、Vite 代理与本地 CLI 继续可用。
- 铁路 HSTORE 标签使用线性解析，避免畸形输入造成正则指数回溯。
- 铁路验收脚本只连接指定 loopback HTTP 端点，不使用环境代理或跟随重定向；旧 metadata 端点回退保留。
- 铁路图激活/回滚在读写前检查版本名及目录边界。
- 工作流 Actions 固定到完整提交 SHA；E2E 使用明确的仓库前端路径。

完整数据流分析与本地配置行为的适用边界见 [CodeQL 审阅记录](CODEQL_REVIEW.md)。静态扫描告警的误报判断仅适用于可信本地操作者、单用户 loopback 应用，不代表可作为公网或多人共享后端使用。

## 下载与升级

| 平台 | 推荐文件 |
|---|---|
| Windows 10/11 x64 | `Transit2GPX-1.0.1-windows-x64-Setup.exe` |
| Windows x64 便携版 | `Transit2GPX-1.0.1-windows-x64.zip` |
| macOS Apple Silicon | `Transit2GPX-1.0.1-macos-arm64.pkg` |
| macOS Apple Silicon 应用归档 | `Transit2GPX-1.0.1-macos-arm64.tar.gz` |

每个主包和铁路组件 ZIP 都有对应 `.sha256` 文件。铁路组件由应用按需下载；城市数据、PBF 和 graph 仍需按向导准备。升级前建议备份数据库。v1.0.0 标签和附件保持原样。

本版只接受 `127.0.0.1`、`localhost` 和 `[::1]` 的本地 Host；不同 Origin/端口或外部域名反向代理会被拒绝。这是新增的访问边界，不能用关闭该检查的方式将应用暴露到公网。

## 验证与限制

最终源码提交、CI、CodeQL、双平台构建和摘要核验结果记录在 GitHub Release 正文及验证附件中。

安装包未做 Windows Authenticode、Apple Developer ID 签名或 macOS 公证，未宣称通过完整恶意软件扫描。本次不重新执行外部 Fog of World 实机验收；保留 GPX 格式、路径与保存流程的自动回归。当前不提供 Intel Mac 安装包。
