# 首次使用指南

[返回项目首页](../README.md)

## 先从一条地铁行程开始

可先下载 [v1.0.0-rc.1 预发布安装包](https://github.com/Uddoo/transit2fog/releases/tag/v1.0.0-rc.1)：Windows x64 解压后运行程序，macOS Apple Silicon 使用 PKG 或 TAR.GZ。安装包无需 Python、Node.js、npm 或 uv；当前尚未签名、公证，具体安装说明见[安装包文档](PACKAGING.md)。

启动安装包会自动打开本地页面，首次使用向导会带你完成环境检查、地铁数据导入和可选的铁路服务准备。第三方数据仍需自行下载，可直接从下面第 2 步开始准备数据。

如果选择源码运行，首次准备还需下载开发依赖。当前支持 Windows 10/11 x64 与 macOS，需要 Node.js 22+、npm 10+ 和 `uv` 0.9+。Windows 还需要 PowerShell 7；不要求 WSL、Git Bash 或 GNU Make。以下终端命令针对源码运行。

### 1. 获取源码并检查环境

先安装 [Git](https://git-scm.com/)，然后在终端运行：

```sh
git clone https://github.com/Uddoo/transit2fog.git
cd transit2fog
```

以下命令均在仓库根目录执行。

Windows PowerShell 7：

```powershell
.\transit2fog.ps1 doctor
.\transit2fog.ps1 setup
```

macOS：

```bash
make doctor
make setup
```

`doctor` 只检查环境，不下载或修改数据；`setup` 根据锁文件安装 Python 和前端依赖。

### 2. 获取一份地铁数据

请先阅读下方兼容提示，选择可用来源并完整解压到仓库外目录：

| 来源 | 适合场景 | 导入时应看到的主文件 |
|---|---|---|
| [CPTOND-2025 v2](https://doi.org/10.6084/m9.figshare.29377427) | CC BY 4.0；当前包存在字段兼容问题，见下方提示 | `metro_routes.shp`、`metro_stops.shp` |
| [Science Data Bank 46 城时序数据](https://doi.org/10.57760/sciencedb.33335) | 已有历史验收的兼容源，CC BY-NC-SA 4.0 | `metro_routes.shp`、`metro_routes_segment_timeline.shp`、`metro_stations_timeline.shp` |

> **当前数据兼容提示（2026-09-08）：** 本次核对的 Figshare v2 `CPTOND-2025.zip`（文件 ID `58153174`）中，全国与上海 `metro_routes.shp` 缺少现有导入器要求的 `route_id` 字段，会被数据审计拒绝。首次使用优先选择表中的 Science Data Bank 兼容源；它曾通过项目的 46 城整包验收，本次未重新下载验证。不要手工补造字段来绕过检查。

不要只复制 `.shp`。每组 Shapefile 必须同时保留同名的 `.shx`、`.dbf`、`.prj`；文件可以位于所选目录的任意子层级。

### 3. 启动并导入

Windows PowerShell 7：

```powershell
.\transit2fog.ps1 dev
```

macOS：

```bash
make dev
```

1. 打开 `http://127.0.0.1:5173/settings/data`。
2. 在“地铁数据”中填写解压目录的绝对路径，点击“导入数据目录”。
3. 等待状态变为“真实地铁数据已就绪”，并确认阻断线路数量符合预期。
4. 如果导入失败，先检查 Shapefile sidecar、CRS 和页面中的质量报告。

### 4. 创建行程并导出 GPX

1. 打开“添加行程”，选择城市、线路、起点和终点。
2. 预览候选；环线、换乘或模糊结果需要人工确认。
3. 保存后打开“导出”，先用少量行程生成 journey GPX 抽检，再按需生成 coverage GPX。
4. 将 GPX 导入目标轨迹应用，确认轨迹没有错误直线或明显跳点；例如可使用《世界迷雾》。

生产模式在 Windows 使用 `.\transit2fog.ps1 start`，在 macOS 使用 `make start`；二者都由单一 FastAPI 服务在 `http://127.0.0.1:8765` 托管 API 和前端。行程页默认使用 OpenStreetMap 在线底图；可通过环境变量关闭或替换为合规的自托管瓦片服务。更完整的数据格式、隔离验证和故障排查见[开发与运行](DEVELOPMENT.md)。

## 铁路最短可用路径

铁路数据下载已经脚本化，但首次使用还需要构建 OpenRailRouting sidecar 和本地图。Java 17+ 可以运行，Windows 当前验证基线为项目内 Temurin 21.0.12.1+1；系统 Maven 和系统级 JDK 安装都不是必需项，脚本会下载并校验固定版本。

### 1. 先选择图范围

| 方案 | 固定数据 | 验证集合 | 建议资源 | 适合场景 |
|---|---|---|---|---|
| 长三角轻量图 | 上海、江苏、浙江、安徽合并 PBF，参考成品约 223 MB | 4 条跨省/高普速线路 | 至少 3 GB 可用磁盘、4 GB 可用内存 | 首次体验、开发调试 |
| 全国完整图 | 中国 PBF 约 1.58 GB，graph 约 187 MB | 8 条全国代表线路 | 至少 5 GB 可用磁盘、4 GB 可用内存 | 全国行程、正式使用 |

全国图在验收机器上建图约 166 秒、峰值 RSS 约 1.46 GB；首次 bootstrap 还会下载并编译固定版本依赖，实际耗时取决于网络和机器。以上是保守准备建议，不是跨平台最低配置承诺。

### 2. 首次准备

先检查核心和铁路环境：

Windows PowerShell 7：

```powershell
.\transit2fog.ps1 setup
.\transit2fog.ps1 setup-java
.\transit2fog.ps1 doctor-rail
.\transit2fog.ps1 rail-fixture
.\transit2fog.ps1 rail-fixture-verify
```

macOS：

```bash
make setup
make doctor-rail
make rail-bootstrap
```

Windows 的 `setup-java` 会把固定版本 JDK 安装到被忽略的项目数据目录，不修改系统 `PATH`、`JAVA_HOME` 或注册表。`rail-fixture` 会完成固定 OpenRailRouting/GraphHopper 构建及最小图生成；`rail-fixture-verify` 会启动 sidecar、验证路由与两个 metadata 端点，再按已确认的进程树停止服务并检查端口释放。

选择长三角轻量图：

Windows PowerShell 7：

```powershell
.\transit2fog.ps1 rail-yangtze-data
.\transit2fog.ps1 rail-yangtze-graph
```

macOS：

```bash
make rail-yangtze-data
make rail-yangtze-graph
```

或者选择全国完整图：

Windows PowerShell 7：

```powershell
.\transit2fog.ps1 rail-china-data
.\transit2fog.ps1 rail-china-graph
```

macOS：

```bash
make rail-china-data
make rail-china-graph
```

下载支持断点续传，并按仓库固定 manifest 校验摘要；PBF、graph 和构建产物都保存在被忽略的 `data/` 目录。

### 3. 验证、激活并一体化启动

新图首次激活时仍需临时启动该明确版本，以便固定样本验证其身份；完成 `*-activate` 后即可关闭临时 sidecar。详细步骤见 [`rail-routing/README.md`](../rail-routing/README.md)。后续日常运行只需一个命令，FastAPI 会启动、验证并监督 active sidecar：

Windows PowerShell 7：

```powershell
.\transit2fog.ps1 dev-rail
# 生产模式：.\transit2fog.ps1 start-rail
```

macOS：

```bash
make dev-rail
# 生产模式：make start-rail
```

主进程只绑定 loopback，复用身份一致的既有 sidecar，并只在退出时回收自己启动的 Java 进程。sidecar 启动失败不会阻断地铁功能；诊断写入应用数据目录的 `logs/rail-sidecar.log`。安装包、进程身份校验和外部 graph/PBF 布局见 [`docs/PACKAGING.md`](PACKAGING.md)。

如果已有图位于旧验收目录或其他自定义位置，请在启动前设置工作目录与图目录；`make doctor-rail` 会显示它实际检查到的 JAR 和 `active` 图：

Windows PowerShell 7：

```powershell
$env:RAIL_WORK_DIR = 'D:\Transit2Fog\rail-work'
$env:RAIL_GRAPH_ROOT = 'D:\Transit2Fog\graphs'
.\transit2fog.ps1 doctor-rail
```

macOS：

```bash
export RAIL_WORK_DIR=/absolute/path/to/rail-work
export RAIL_GRAPH_ROOT=/absolute/path/to/graphs
make doctor-rail
```
