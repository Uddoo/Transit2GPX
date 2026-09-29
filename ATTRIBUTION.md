# 数据与第三方署名

Transit2GPX（原 Metro2Fog）的项目程序代码采用 [Apache License 2.0](LICENSE)；第三方运行库和导入数据分别遵循各自的许可证。本文件记录数据层署名要求；它不替代项目或各依赖自身的许可证文本。

## 地铁数据

- CPTOND-2025：应用在数据版本记录、设置页和 GPX metadata 中保留数据集名称、版本、来源 URL、捕获时间、校验和与导入时识别到的许可证。
- Science Data Bank 的中国城市地铁修建时序数据集（1971–2025）：页面标注 CC BY-NC-SA 4.0；导入器必须保留 DOI `10.57760/sciencedb.33335` 与该许可证，不得误标为 CPTOND Figshare 原包。
- 完整第三方地铁数据不提交到本代码仓库。

## OpenStreetMap 与 Geofabrik

当前在线底图和铁路几何使用 OpenStreetMap 数据。交互地图必须在地图附近显示可读署名：

```text
© OpenStreetMap contributors
```

署名应链接到 <https://www.openstreetmap.org/copyright>，使用户能够查看 ODbL 1.0 信息。

铁路 PBF 由 Geofabrik 提供。应用记录提取文件 URL、数据时间和校验和，并在铁路数据设置或详情中同时说明：

```text
Data © OpenStreetMap contributors, available under ODbL 1.0.
Extract provided by Geofabrik GmbH.
```

默认仓库不分发 PBF、OpenRailRouting graph cache 或全国铁路派生数据库。若未来公开分发这些数据库，必须先评估并履行 ODbL 对数据库/衍生数据库的署名、许可和提供方式要求。

## OpenRailRouting

铁路路径引擎使用固定提交的 Geofabrik OpenRailRouting 与 GraphHopper fork。发布或打包 sidecar 时，应保留其 `LICENSE.txt`、`THIRD_PARTY.md` 及所有随附第三方声明，并记录实际使用的提交或发布版本。

## 参考

- <https://www.openstreetmap.org/copyright>
- <https://osmfoundation.org/wiki/Licence/Attribution_Guidelines>
- <https://download.geofabrik.de/asia/china.html>
- <https://github.com/geofabrik/OpenRailRouting>
