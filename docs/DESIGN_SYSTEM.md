# Transit2Fog 视觉与交互设计系统

## 1. 视觉基准

本设计系统由 2026-08-20 生成并审阅的产品概念图固化；概念图保留在设计审阅记录中，不作为运行时资产提交。

原图为 1536×1024，包含桌面添加行程、窄屏添加行程、CSV 审核表格和 GPX 导出汇总四个状态。它是实现的视觉规范；所有可交互文字与控件必须由 HTML/CSS/React 渲染，不能把概念图作为界面背景。

## 2. 设计方向

- 气质：现代中文交通控制台，精确、克制、可信。
- 画布：真白 `#ffffff`，辅助区域使用极浅冷灰。
- 核心结构：开放式 rail、表格和地图画布；只在需要明确边界时使用薄边框容器。
- 视觉焦点：青绿色选中线路、站点节点和当前任务。
- 禁止：营销 hero、渐变、玻璃拟态、bento/card grid、装饰性徽章、伪指标、照片和无意义阴影。

## 3. Design tokens

### 3.1 颜色

```css
--color-canvas: #ffffff;
--color-subtle: #f6f9fa;
--color-subtle-strong: #eef4f5;
--color-text: #112333;
--color-text-muted: #647682;
--color-text-faint: #8b9aa4;
--color-border: #cdd9df;
--color-border-strong: #aebec7;
--color-accent: #079aa4;
--color-accent-strong: #007f89;
--color-accent-soft: #e3f5f6;
--color-success: #128a55;
--color-success-soft: #e9f7ef;
--color-warning: #e68429;
--color-warning-soft: #fff4e6;
--color-danger: #df3d49;
--color-danger-soft: #fff0f1;
--color-map-line-muted: #c8d4da;
--color-focus: #006fba;
```

颜色不是状态的唯一编码。每个状态同时使用图标/短文本和左侧 3px 状态条。

### 3.2 字体

```css
--font-ui: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", system-ui, sans-serif;
--font-mono: "SFMono-Regular", "Roboto Mono", ui-monospace, monospace;
```

| 角色 | 字号/行高 | 字重 |
|---|---|---|
| 页面标题 | 24/32 | 650 |
| 区域标题 | 18/26 | 650 |
| 导航/主要控件 | 14/20 | 550 |
| 正文/输入 | 14/22 | 400–500 |
| 标签 | 12/18 | 550 |
| 数据注释 | 12/18 | 400，必要时 mono |

控件字体必须显式定义，不依赖浏览器默认值。

### 3.3 间距与几何

```css
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-5: 20px;
--space-6: 24px;
--space-8: 32px;
--space-10: 40px;
--radius-sm: 8px;
--radius-md: 12px;
--radius-lg: 16px;
--control-height: 42px;
--touch-target: 44px;
--border-width: 1px;
--icon-stroke: 1.75px;
```

阴影仅用于移动端候选 bottom sheet 与确有遮挡层级的浮层，桌面结构依靠边框和背景区分。

## 4. 容器模型

### 桌面，宽度 ≥ 1024px

- 176px 固定左侧导航 rail。
- 顶部 56px utility bar，只展示本地数据状态。
- 页面内容使用 20–24px gutter。
- 添加行程主体为约 260px 表单列 + 自适应地图画布。
- 候选路径为地图下方单行 rail，不拆成多张卡片。

### 平板，720–1023px

- 左侧导航收窄为 72px 图标 rail，标签通过可访问 tooltip 或展开菜单提供。
- 表单和地图允许 320px/剩余宽度分栏；空间不足时顺序堆叠。

### 窄屏，< 720px

- 顶部 compact bar + 底部五项导航；触控目标至少 44px。
- 表单变为全宽行列表；可选字段仍保留清晰标签。
- 地图高度约 260–320px，不允许横向溢出。
- 候选路径为 map 后的常规 bottom section；操作按钮并排或按 1:1 比例排列。

## 5. 组件族

- `AppShell`：桌面 sidebar、移动 topbar/bottom nav、utility status。
- `NavItem`：outline 图标、标签、selected 的 accent soft 背景。
- `Field`：label、optional 文案、控件、错误/帮助文本。
- `Button`：primary、secondary、danger、quiet；都有 focus-visible。
- `TransitMap`：Leaflet 画布、线路、站点、起终点 label、简洁缩放控件。
- `CandidateRail`：候选标题、线路摘要、站数/距离、质量状态、操作。
- `StatusMark`：图标 + 文本 + 状态条，禁止仅用颜色。
- `ReviewTable`：sticky header、行状态、筛选 rail、分页。
- `ExportSummary`：模式选择、数值列表、点间距 radio group、生成操作。
- `EmptyState`/`ErrorState`：说明原因和唯一明确的下一步，不使用装饰插画。

## 6. 图标清单

图标统一使用 24×24 viewBox、圆头圆角、`currentColor`、1.75px stroke。优先使用同一 outline icon family，并按语义直接导入单图标，避免 barrel import。

| 位置 | 图标语义 |
|---|---|
| 品牌 | 地铁车头/站点 |
| 行程 | 列表 |
| 添加行程 | 圆内加号 |
| CSV 导入 | 下载到托盘 |
| 导出 | 向外箭头 |
| 数据与设置 | 齿轮 |
| 数据状态 | database/file-check |
| 预览路径 | 眼睛 |
| 站数 | train/front |
| 距离 | ruler |
| 已验证 | circle-check |
| 需确认 | triangle-alert |
| 未解析 | circle-alert |

## 7. 允许的首屏文案

实现首屏不得在未更新本文件时增加营销性或解释性文案。允许内容：

- `Transit2Fog`
- `行程`、`添加行程`、`CSV 导入`、`导出`、`数据与设置`
- `CPTOND-2025 · 数据就绪`（未就绪时允许换成真实状态）
- `添加一段真实乘坐记录`
- `选择城市、线路与起终点，确认后再保存。`
- 字段：`城市`、`线路`、`起点站`、`终点站`、`方向（可选）`、`途经站（可选）`、`乘坐日期（可选）`、`备注（可选）`
- `预览路径`
- `候选路径`
- `返回修改`、`保存行程`
- 路径数据：线路名、站名、站数、距离和质量状态。

## 8. 动效

- 路由页面切换不做大幅 motion。
- 候选 rail 在解析后以 160ms opacity/translateY 进入。
- 选中线路更新使用 120ms stroke/color transition。
- 异步状态用文本和进度条，不使用持续旋转作为唯一反馈。
- `prefers-reduced-motion: reduce` 时移除所有非必要 transition。

## 9. 核心交互验收

1. 用户可仅用键盘完成城市、线路、站点选择和路径预览。
2. 地图点击不是唯一选站方式。
3. 候选出现后焦点移到候选标题；返回修改恢复到触发按钮。
4. 窄屏底部导航不会遮挡候选按钮或表单末尾。
5. CSV 表格在窄屏使用受控横向滚动，并保留行号与状态列可辨识。
6. 导出模式和点间距使用原生 radio 语义。
