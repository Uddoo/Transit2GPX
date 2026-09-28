# 安装包与一体化铁路运行

## 当前获取状态

当前代码版本为 1.0.0，尚无正式 GitHub Release 安装包。可以先按[首次使用指南](GETTING_STARTED.md)运行源码，或按本文自行构建。

2026-09-08 的[双平台构建](https://github.com/Uddoo/transit2fog/actions/runs/34192998619)已生成 Windows x64 ZIP、macOS arm64 PKG 与备用 TAR.GZ，并通过工作流内隔离 smoke test。它们仍是未签名的验证产物；文件选择、摘要、验证范围和发布前剩余事项见[发行说明草稿](RELEASE_DRAFT.md)。Actions artifact 有保留期限，不是长期下载入口。

## 1. 产物

发布工作流 `.github/workflows/package.yml` 在 Windows x64 与 macOS runner 上使用锁定的 Python、Node.js、OpenRailRouting 和 GraphHopper 版本生成：

- Windows：`Transit2Fog-<version>-windows-x64.zip`，包含独立可执行目录、用户级 `install.ps1` / `uninstall.ps1` 和 SHA-256 文件。
- macOS：`Transit2Fog-<version>-macos-<arch>.pkg` 以及同内容的 `.tar.gz` 备用包，并生成 SHA-256 文件。

安装包内含生产前端、FastAPI、Python 地理运行库、Alembic migrations、GPX schema、铁路 Profile/config，以及发布工作流构建的 OpenRailRouting sidecar JAR。它不包含 OSM PBF、GraphHopper graph cache 或用户数据库。

当前产物未做 Apple Developer ID 或 Windows Authenticode 签名，也不包含自动更新。正式向第三方分发前必须在受控发布环境完成签名、公证和恶意软件扫描。

## 2. 本地构建

```powershell
# Windows PowerShell 7
.\transit2fog.ps1 package

# 把已固定构建的 sidecar 一并放入包内
.\transit2fog.ps1 package `
  -SidecarJar .\data\rail-routing\dist\openrailrouting.jar
```

```sh
# macOS
make package
make package SIDECAR_JAR="$PWD/data/rail-routing/dist/openrailrouting.jar"
```

构建命令会：

1. 构建并验证五个前端路由懒加载 chunk；
2. 使用 PyInstaller 生成独立目录；
3. 在隔离临时数据目录执行 Alembic、API/地理库和资源 smoke test；
4. 创建平台包和 SHA-256 文件。

提供 sidecar JAR 时，构建会拒绝缺少 OpenRailRouting/GraphHopper LICENSE、NOTICE 或 THIRD_PARTY 声明的工作目录。

## 3. Windows 安装与卸载

解压 ZIP 后运行：

```powershell
pwsh -NoLogo -NoProfile -File .\Transit2Fog\install.ps1
```

默认安装到 `%LOCALAPPDATA%\Programs\Transit2Fog`，并创建普通模式和 `Transit2Fog Railway` 两个开始菜单快捷方式。不要求管理员权限，不修改防火墙、系统 `PATH` 或执行策略。

卸载只删除程序文件和快捷方式：

```powershell
pwsh -NoLogo -NoProfile -File .\Transit2Fog\uninstall.ps1
```

数据库、备份、PBF 和 graph cache 位于独立应用数据目录，安装升级和卸载均不会删除。

## 4. 一体化 sidecar

源码运行不再需要单独的 sidecar 终端：

```powershell
.\transit2fog.ps1 start-rail
# 或开发模式
.\transit2fog.ps1 dev-rail
```

```sh
make start-rail
make dev-rail
```

主进程会完成以下操作：

- 解析安全的 `active.json`/相对 selector；
- 验证 graph metadata、PBF SHA-256、Profile 和 OpenRailRouting commit；
- 只在 loopback 端口启动 Java sidecar；
- 若端口上已有身份一致的 sidecar，则复用但不终止它；
- 对自己启动的 Java 进程记录 `logs/rail-sidecar.log` 并在退出时回收；
- sidecar 缺失或失败时保留地铁功能，由铁路状态 API 显示不可用原因。

安装包铁路模式使用：

```text
Transit2Fog.exe --rail
Transit2Fog.app/Contents/MacOS/Transit2Fog --rail
```

铁路运行仍需 Java 17+（验证基线为 21）、已验证并激活的 graph，以及与 metadata checksum 一致的 PBF。默认布局为应用数据目录下：

```text
rail-routing/
├── graphs/active.json
├── graphs/<graph-version>/...
└── regions/<region-version>/<file>.osm.pbf
```

也可通过 `--rail-graph-root`、`--rail-pbf`、`--rail-sidecar-jar` 或对应 `TRANSIT2FOG_RAIL_*` 环境变量指定外部位置。sidecar 始终只接受无凭据的 loopback HTTP 地址。
