# Windows 原生运行

Transit2Fog 可以在 Windows 10 22H2 或 Windows 11 x64 上直接从源码运行。Windows 入口是仓库根目录的 `transit2fog.ps1`，不要求 WSL、Git Bash、GNU Make，也不会修改 PowerShell 执行策略。

## 1. 环境

必需组件：

- PowerShell 7（`pwsh`）。
- Node.js 22+ 与 npm 10+。
- `uv` 0.9+；Python 3.11 环境由 `uv` 根据 `backend/uv.lock` 管理。
- Git for Windows；只在克隆仓库及准备可选铁路 sidecar 时使用。

铁路能力另外需要完整 JDK 17+，当前可复现基线是 JDK 21。只安装 JRE 不够，因为 bootstrap 需要 `jar.exe`。可以把 JDK 的 `bin` 加入 `PATH`，也可以仅为当前 PowerShell 会话指定：

```powershell
$env:RAIL_JAVA_HOME = 'C:\Program Files\Java\jdk-21'
```

Windows 入口还会自动发现项目专用便携 JDK：`data\rail-routing\tools\temurin-21`。该目录受 `.gitignore` 保护，不修改系统 `PATH`、`JAVA_HOME` 或注册表；显式设置的 `RAIL_JAVA_HOME` 仍具有最高优先级。

按仓库固定的 Windows x64 Temurin 21 版本下载、校验并安装便携 JDK：

```powershell
.\transit2fog.ps1 setup-java
```

下载信息与 SHA-256 固定在 `rail-routing\jdk-windows.json`；安装脚本还会读取发布方 checksum 文件并在解压前复核本地文件摘要。

## 2. 首次安装与检查

在仓库根目录打开 PowerShell 7：

```powershell
.\transit2fog.ps1 doctor
.\transit2fog.ps1 setup
.\transit2fog.ps1 doctor
```

第一次 `doctor` 允许提示依赖尚未安装；`setup` 根据两个锁文件创建 `backend\.venv` 并安装 `frontend\node_modules`。第二次 `doctor` 应不再出现这两项提醒。

如果系统策略阻止直接执行脚本，先确认当前终端确实是 PowerShell 7，然后使用不会修改系统策略的显式入口：

```powershell
pwsh -NoLogo -NoProfile -File .\transit2fog.ps1 doctor
```

不要为了运行本项目把机器级执行策略改为 `Unrestricted`。

## 3. 开发与生产运行

开发模式同时启动 FastAPI 与 Vite；退出前端进程时，脚本会清理它启动的后端子进程：

```powershell
.\transit2fog.ps1 dev
```

- 前端：`http://127.0.0.1:5173`
- API：`http://127.0.0.1:8765`
- API 文档：`http://127.0.0.1:8765/api/docs`

生产模式先构建前端、升级数据库，再由 FastAPI 在一个端口托管 API 与 SPA：

```powershell
.\transit2fog.ps1 start
```

服务默认只监听 `127.0.0.1:8765`。脚本不会创建 Windows 服务、防火墙规则、登录启动项或局域网监听。

## 4. 检查与测试

```powershell
.\transit2fog.ps1 check
.\transit2fog.ps1 e2e
```

`check` 包含后端 Ruff、格式检查、Mypy、pytest/coverage，以及前端 ESLint、Vitest 和生产构建。`e2e` 需要 Playwright Chromium；若浏览器尚未安装，可在完成 `setup` 后执行：

```powershell
Set-Location .\frontend
npm exec -- playwright install chromium
Set-Location ..
```

常用的较小范围命令：

| 目的 | 命令 |
|---|---|
| 只检查后端 | `.\transit2fog.ps1 backend-check` |
| 只检查前端 | `.\transit2fog.ps1 frontend-check` |
| 只运行单元测试 | `.\transit2fog.ps1 test` |
| 只构建前端 | `.\transit2fog.ps1 build` |
| 只升级数据库 | `.\transit2fog.ps1 db-upgrade` |

## 5. Windows 路径与应用数据

PowerShell 中含空格或中文的路径应使用单引号。应用数据默认由 `platformdirs` 放在当前 Windows 用户的数据目录；可在启动命令前覆盖：

```powershell
$env:TRANSIT2FOG_DATA_DIR = 'D:\Transit2Fog\app-data'
$env:TRANSIT2FOG_DATABASE_URL = 'sqlite:///D:/Transit2Fog/app-data/transit2fog.sqlite3'
.\transit2fog.ps1 start
```

SQLite URL 建议使用正斜杠。不要把 Windows 路径写成 `sqlite://D:\...`；该形式不是项目所需的绝对 SQLite URL。

导入真实 CPTOND 数据时，界面可以直接接收 Windows 绝对路径。隔离验证命令为：

```powershell
.\transit2fog.ps1 validate-real-data -CptondDir 'D:\Datasets\CPTOND-2025'
```

备份命令不会覆盖已有 ZIP：

```powershell
.\transit2fog.ps1 backup -OutputPath 'D:\Backups\transit2fog-backup.zip'
```

## 6. 铁路 sidecar

先检查完整环境：

```powershell
.\transit2fog.ps1 doctor-rail
```

长三角路径：

```powershell
.\transit2fog.ps1 rail-bootstrap
.\transit2fog.ps1 rail-yangtze-data
.\transit2fog.ps1 rail-yangtze-graph
```

构建最小 Cologne fixture 并在同一命令内完成 sidecar 路由、metadata 与端口清理验收：

```powershell
.\transit2fog.ps1 rail-fixture
.\transit2fog.ps1 rail-fixture-verify
```

完成建图后使用两个 PowerShell 7 终端：

```powershell
# 终端 A
.\transit2fog.ps1 rail-yangtze-start
```

```powershell
# 终端 B；首次运行或切换图版本时先验证并激活
.\transit2fog.ps1 rail-yangtze-activate
.\transit2fog.ps1 dev-rail
```

全国图把命令中的 `yangtze` 换为 `china`。构建文件默认位于仓库下被忽略的 `data\rail-routing`；也可在两个终端中设置完全相同的外部目录：

```powershell
$env:RAIL_WORK_DIR = 'D:\Transit2Fog\rail-work'
$env:RAIL_GRAPH_ROOT = 'D:\Transit2Fog\graphs'
.\transit2fog.ps1 doctor-rail
```

`active.json` 与 `previous.json` 只保存经过验证的单段版本名，并通过同目录临时文件原子替换。它们替代 Windows 上通常需要额外权限的目录符号链接；读取逻辑仍兼容既有的安全相对符号链接。selector 不复制或修改不可变 graph 目录。

切换异常时：

```powershell
.\transit2fog.ps1 rail-rollback
```

随后重启终端 A 的 sidecar，使运行图与 `active` selector 一致。

## 7. 命令对应关系

Windows 的 `.\transit2fog.ps1 <command>` 与 macOS 的 `make <target>` 使用相同的命令名，包括 `doctor`、`setup`、`dev`、`dev-rail`、`build`、`start`、`check`、`test`、`e2e`、`db-upgrade`、`rail-bootstrap`、`rail-yangtze-*`、`rail-china-*` 和 `rail-rollback`。

两个需要参数的命令使用 PowerShell 命名参数：

```powershell
.\transit2fog.ps1 validate-real-data -CptondDir <directory>
.\transit2fog.ps1 rail-build-graph -PbfPath <file.osm.pbf> -GraphVersion <version>
```

## 8. 常见故障

- `doctor` 找到 Windows PowerShell 5.1 而不是 7：从开始菜单打开 PowerShell 7，或明确使用 `pwsh -File`。
- `npm` 或 `uv` 在新安装后仍找不到：关闭并重新打开 PowerShell，让新的 `PATH` 生效。
- `doctor-rail` 报缺少 `java.exe` / `jar.exe`：安装完整 JDK 21，或设置 `RAIL_JAVA_HOME`。
- 端口 5173、8765、8989 或 8990 已被占用：先确认占用进程；不要直接结束未核实归属的系统或其他项目进程。
- Windows Defender 首次扫描大量 Python/Node 文件导致安装较慢：先观察 `uv`、`npm` 及磁盘活动；不要在没有证据时关闭防护软件。
- 路径超过旧式 Windows 限制：优先把仓库和铁路工作目录放在较短路径，例如 `F:\Dev\Transit2Fog` 与 `D:\T2F\rail`。
