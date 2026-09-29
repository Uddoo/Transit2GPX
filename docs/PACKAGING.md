# 安装包与一体化铁路运行

## 当前获取状态

首个 [v1.0.0-rc.1 预发布版](https://github.com/Uddoo/transit2fog/releases/tag/v1.0.0-rc.1)已提供 Windows x64 ZIP、macOS Apple Silicon PKG 与备用 TAR.GZ，以及各文件的 SHA-256。包内应用版本为 1.0.0；当前尚无 Intel Mac 安装包。

安装包自带 Python 运行库与生产前端，不要求安装 Python、Node.js、npm 或 uv。Windows 安装脚本需要 PowerShell 7；铁路模式仍需 Java 和用户准备的图数据。文件选择、构建记录与验证范围见[发行说明](RELEASE_DRAFT.md)。请从 Release 下载，Actions artifact 仅用于构建验证且有保留期限。

## 1. 轻量安装包（下一次发布）

第二轮同时引入[标准城市数据包](CITY_PACKS.md)：基础包排除 GeoPandas/Pandas/Pyogrio/GDAL，使用 `.t2fcity` 文件导入地铁数据。需要原始 Shapefile 导入的用户可构建 `--with-import-tools` 完整导入版。铁路站点仍可直接从 PBF 导入。

以下描述当前源码新增的打包方式；**v1.0.0-rc.1 附件不会随源码修改而变化**。

发布工作流 `.github/workflows/package.yml` 在 Windows x64 与 macOS runner 上使用锁定的 Python、Node.js、OpenRailRouting 和 GraphHopper 版本生成：

- Windows：推荐 `Transit2Fog-<version>-windows-x64-Setup.exe`，双击安装，不要求 PowerShell 或管理员权限；保留 `.zip` 便携包及原有安装脚本作为备用。
- macOS：`Transit2Fog-<version>-macos-<arch>.pkg` 以及同内容的 `.tar.gz` 备用包，并生成 SHA-256 文件。
- 按平台附带 `Transit2Fog-rail-components-<platform>.zip`，包含固定提交的 OpenRailRouting JAR、应用专用 Temurin 21 JRE 和完整相关许可。普通用户无需手动下载该附件。

默认主包内含生产前端、FastAPI、Python 地理运行库、Alembic migrations、GPX schema、铁路 Profile/config 和固定组件下载清单。主包不再包含铁路 JAR，也不包含地铁数据、OSM PBF、GraphHopper graph cache 或用户数据库。

第一次使用铁路时，在首次使用向导的“铁路服务”步骤点击“下载并准备铁路组件”。程序显示下载大小及进度，支持失败重试、分段续传、已下载文件校验和已安装组件复用。完成后继续填写铁路图和 PBF，再启动服务、导入车站索引。**组件就绪不代表铁路数据就绪**；城市/区域预处理数据包不在本轮范围内。

组件清单随主包固定下载地址、平台、大小、SHA-256、Java 版本和 sidecar 提交。仅使用 HTTPS，先校验再解压，并拒绝路径穿越、链接、重复路径和超出清单大小的归档。安装在独立暂存目录中，实际执行 `java -version` 成功后再切换为完整目录。不会修改系统 PATH、JAVA_HOME 或全局 Java；手动指定的 Java/JAR 路径仍优先。

这降低首次下载量；使用铁路时仍需下载相应组件。完整 JRE 是首轮可靠性选择，本轮未采用未经铁路验证的 jlink 裁剪。

当前产物未做 Apple Developer ID 或 Windows Authenticode 签名，也不包含自动更新。正式向第三方分发前必须在受控发布环境完成签名、公证和恶意软件扫描。

预发布包可能触发系统的未识别开发者提示；本次发布不代表已完成签名、公证或恶意软件扫描，也不要求关闭系统安全防护。下载后用对应 `.sha256` 核对文件，例如 macOS 使用 `shasum -a 256 <文件>`，Windows PowerShell 使用 `Get-FileHash <文件> -Algorithm SHA256`。

## 2. 本地构建

发布工作流使用以下轻量构建命令。`--release-tag` 必须是将要上传组件附件的**确切标签**，不能使用 `latest`。先通过既有 `rail-bootstrap` 构建 sidecar。

```powershell
# Windows：构建工具只安装到指定工具目录；应用用户无需安装这些工具
$iscc = .\scripts\setup_inno.ps1 -Destination "$env:TEMP\transit2fog-inno"
uv run --project backend python scripts/build_package.py `
  --sidecar-jar data/rail-routing/dist/openrailrouting.jar `
  --rail-components --release-tag <待发布标签> `
  --windows-installer --iscc $iscc
```

```sh
# macOS Apple Silicon
uv run --project backend python scripts/build_package.py \
  --sidecar-jar data/rail-routing/dist/openrailrouting.jar \
  --rail-components --release-tag <待发布标签>
```

JRE 下载地址和 SHA-256 锁定在 `packaging/java-runtimes.json`；构建时先验证官方归档，再保留完整 `legal` 和许可证目录。Windows 编译器由 `scripts/setup_inno.ps1` 固定为 Inno Setup 6.7.1，并校验 SHA-256 与发布者签名。CI 的手动构建使用 `preview-<commit>` 地址，仅供验证，不会自动发布；对应标签未发布前，不能宣称在线下载入口已经可用。

以下旧命令仍支持不带在线组件清单的本地/高级构建，以及内置 JAR 的兼容构建：

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

1. 构建并验证七个前端路由懒加载 chunk；
2. 使用 PyInstaller 生成独立目录；
3. 在隔离临时数据目录执行 Alembic、API/地理库和资源 smoke test；
4. 创建平台包和 SHA-256 文件。

提供 sidecar JAR 时，构建会拒绝缺少 OpenRailRouting/GraphHopper LICENSE、NOTICE 或 THIRD_PARTY 声明的工作目录。

## 3. Windows 安装与卸载

推荐双击 `Setup.exe`：默认用户级安装到 `%LOCALAPPDATA%\Programs\Transit2Fog`，创建开始菜单入口，桌面快捷方式可选，安装完成后可直接启动。使用系统“已安装的应用”卸载。升级会清除旧版程序目录内的内置 JAR 和旧安装脚本，不触及应用数据目录。

旧向导曾把自动发现的 JAR 路径保存为偏好。轻量升级后若该旧默认文件已不存在，启动时恢复自动发现；自定义路径和明确的启动参数仍保留。

使用备用 ZIP 的用户可直接运行 EXE，或用 PowerShell 7 安装：

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

铁路运行需 Java 17+（轻量版组件自动提供 21）、已验证并激活的 graph，以及与 metadata checksum 一致的 PBF。默认布局为应用数据目录下：

```text
rail-routing/
├── components/<组件 SHA-256>/java/...
├── components/<组件 SHA-256>/openrailrouting.jar
├── graphs/active.json
├── graphs/<graph-version>/...
└── regions/<region-version>/<file>.osm.pbf
```

也可通过 `--rail-graph-root`、`--rail-pbf`、`--rail-sidecar-jar` 或对应 `TRANSIT2FOG_RAIL_*` 环境变量指定外部位置。sidecar 始终只接受无凭据的 loopback HTTP 地址。
