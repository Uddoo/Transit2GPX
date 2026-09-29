# 展示素材与数据说明

[返回项目首页](../README.md)

## 改名封面（2026-09-29）

README 现使用 [social-preview-transit2gpx.png](images/social-preview-transit2gpx.png)。使用内置 ImageGen 编辑原封面，将标题改为 Transit2GPX，保留宽幅构图、中文文案、页脚与线路配色。原图及下面的历史实机素材保留；本次没有更新 GitHub 仓库 Social preview 设置，也没有重录演示。

本次编辑提示词：

> Edit this existing project banner. Change ONLY the large English title Transit2Fog to Transit2GPX. Preserve original wide 2:1 aspect ratio, composition, white background, black typography, exact Chinese text, METRO + RAIL → GPX footer, abstract gray and teal network on right. Match title font and size as closely as possible while fitting new title. This is a precise brand rename, no redesign.

## 本次素材（2026-09-08）

| 文件 | 用途 | 来源 |
|---|---|---|
| [metro-route-preview-v2.png](images/metro-route-preview-v2.png) | README 主截图 | 当前代码的真实 FastAPI + 生产前端，上海地铁 6 号线候选 |
| [gpx-export-v2.png](images/gpx-export-v2.png) | 导出设置截图 | 同一隔离环境中实际保存的 1 条演示行程，27 个区间、32.6 km |
| [metro-demo.gif](images/metro-demo.gif) | 可折叠的 20 秒演示 | Playwright 真实操作录像，经 FFmpeg 添加步骤字幕、转码并在结尾延长停留；3 fps、960px 宽 |
| [metro-demo.mp4](images/metro-demo.mp4) | 较小体积的视频版本 | 同一真实录像；字幕位于新增的底部留白，不遮挡地图署名 |
| [social-preview.png](images/social-preview.png) | README 顶部封面与 GitHub 分享封面 | 内置 ImageGen 生成的品牌示意图；抽象线路不是实际地理数据或产品截图 |

地铁与导出截图采集视口为 1440 × 1100，保留页面内容与 OpenStreetMap 署名。原始演示约 14.48 秒，末尾停留延长至 20 秒；该时长不代表首次安装、下载或导入耗时。导出文件已实际下载，GPX 保留在本机演示工作目录，不作为个人乘坐记录发布。

## 演示数据如何准备

源数据为 [CPTOND-2025 Figshare v2](https://doi.org/10.6084/m9.figshare.29377427.v2)，ZIP 文件 ID `58153174`，CC BY 4.0。通过 HTTP Range 读取 ZIP 目录及所需条目，对提取条目逐个验证原 ZIP 的 CRC 和长度；未下载整个约 2.16 GB 压缩包，因此不声称验证了整包摘要。

本次全国与上海原始 `metro_routes.shp` 均缺少现有导入器要求的 `route_id`。为制作隔离演示，对上海数据执行了以下**拍摄专用预处理**：

1. 用精确的 `(city_code, route_cn)` 关联线路表和站点表。
2. 要求每条线路在站点表中只有一个不同的原始 `route_id`，否则拒绝关联。
3. 将该原始 ID 写入拍摄数据的线路表；不改变线路或站点几何。
4. 通过应用导入器建立独立数据库，再用实际 UI 预览、保存、导出。

该预处理不是本次新增的应用功能，也不表示原始 Figshare ZIP 已可直接导入。上海数据导入就绪后，通用验证脚本因需要两个不同城市的普通/复杂线路样本而未通过完整验收；本次只验证上述上海演示路径。用户入门的数据兼容提示见[首次使用指南](GETTING_STARTED.md#2-获取一份地铁数据)。

演示行程备注明确为“GitHub 演示行程（非个人乘坐记录）”。原始数据、预处理结果、数据库和下载 GPX 均保存在被忽略的 `data/github-refresh/`，不提交到仓库。

## 保留的历史素材

[railway-candidates.jpg](images/railway-candidates.jpg) 是此前北京南—上海虹桥真实验收环境的截图。本次没有可用的中国铁路图，未重新拍摄，也未将该图作为本次铁路运行验证证据。原来的地铁与导出 JPG 保留供历史文档使用。

地图底图：© [OpenStreetMap contributors](https://www.openstreetmap.org/copyright)，显示保留 Leaflet / OpenStreetMap 署名。数据许可与完整署名见 [ATTRIBUTION.md](../ATTRIBUTION.md)。

## 分享图生成说明

使用内置 ImageGen，未使用 API Key 或外部图片生成服务。最终文件约 929 kB、2:1 比例，已配置到 GitHub 仓库的 Social preview。

提示词：

> Create a polished GitHub social preview brand graphic for Transit2Fog. White background, restrained black typography, teal #079aa4 route highlight, very pale cool gray abstract transit network on the right. Spacious typography on the left, one highlighted journey connecting round station nodes on the right. Conceptual brand illustration, not a real map or application screenshot. No fake UI, real geography, gradients, glassmorphism, shadows, photographs, download buttons or unsupported claims. Exact text: “Transit2Fog”; “把坐过的地铁和火车，” then “变成地图上的足迹。”; footer “METRO + RAIL → GPX”. High contrast, generous margins, clear Chinese typography.

## 后续更新

功能或 UI 变化后应重新录制真实操作，更新本文件中的日期、数据来源和验证范围。不要以生成式图片替代功能截图；不要把演示时间写成首次安装承诺。GIF 保留在可折叠区域，并提供静态截图、文字步骤与 MP4 版本。
