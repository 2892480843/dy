# 抖音旅行规划 Agent 前端页面说明与优化指南

## 1. 项目概览

本项目是一个“抖音旅行路线复刻 Agent”：

用户粘贴抖音视频链接后，系统会解析视频内容，识别目的地、景点、美食、预算等信息，再结合出发城市、交通、天气、酒店和用户偏好，生成可调整的旅行方案。

当前项目结构：

| 路径 | 说明 |
|---|---|
| `web/` | 前端项目，基于 Next.js、React、Tailwind CSS |
| `api/` | 后端项目，基于 FastAPI |
| `web/app/page.tsx` | 前端核心页面，所有业务页面都集中在这一个文件中 |
| `api/app/main.py` | 后端核心接口，包含抖音解析、旅行规划、交通、图片、TTS 等逻辑 |

当前前端并不是多个路由页面，而是一个 Next.js 首页 `/`，通过 `step` 状态切换成多个业务页面。

核心流程：

```text
entry 首页
  -> parsing 视频解析中
  -> confirm 视频结果确认
  -> transport 出发城市与交通确认
  -> wizard 偏好向导
  -> review 信息复核
  -> planning Agent 生成中
  -> result 最终方案
```

## 2. 页面总览

| step 状态 | 页面名称 | 主要作用 |
|---|---|---|
| `entry` | 首页/链接输入页 | 粘贴抖音链接，启动视频路线分析 |
| `parsing` | 视频解析中页 | 展示抖音视频分析进度 |
| `transition` | 过渡页 | 页面切换时展示短暂加载状态 |
| `confirm` | 视频分析结果确认页 | 确认目的地、博主路线和周边推荐 |
| `transport` | 出发城市与交通页 | 获取/填写出发城市，选择交通方式 |
| `wizard` | 偏好向导页 | 分步收集旅行天数、预算、兴趣 |
| `review` | 信息复核页 | 汇总并允许修改所有出行信息 |
| `planning` | Agent 生成中页 | 流式展示旅行方案生成过程 |
| `result` | 最终方案页 | 展示完整方案，支持朗读和二次调整 |

## 3. 页面详解

### 3.1 首页：`entry`

入口位置：`web/app/page.tsx` 中 `if (step === "entry")`

#### 页面功能

首页用于接收用户的抖音视频链接，是整个流程的起点。

#### 页面内容

- 顶部品牌：`DouTrip Agent`
- 顶部进度条：当前位于“入口”
- Hero 主标题：`复刻抖音旅游攻略视频里的路线和玩法`
- 输入框：用于粘贴抖音链接
- 提醒文案：视频越长，音频转写和路线分析越久
- 主按钮：`分析视频路线`

#### 核心逻辑

用户提交表单后执行 `handleEntrySubmit`：

1. 清空上一次的错误、方案和分析结果。
2. 校验输入内容不能为空。
3. 设置状态为 `parsing`。
4. 调用后端接口 `/api/douyin/analyze/stream`。
5. 读取后端流式返回的视频分析结果。
6. 成功后进入 `confirm` 页面。
7. 失败后回到 `entry` 页面并显示错误信息。

#### 前端优化建议

| 优化点 | 说明 |
|---|---|
| 链接格式校验 | 用户输入非抖音链接时提前提示 |
| 粘贴自动识别 | 监听剪贴板粘贴后自动填充和聚焦按钮 |
| 更明确的错误提示 | 区分链接为空、链接格式错误、后端解析失败 |
| 首页视觉聚焦 | 减少说明文字，把用户注意力集中到输入框和按钮 |

### 3.2 视频解析页：`parsing`

入口位置：`web/app/page.tsx` 中 `if (step === "parsing")`

#### 页面功能

展示系统分析抖音视频的实时进度。

#### 页面内容

- 加载动画
- 当前阶段说明
- 当前进度百分比
- 阶段列表：
  - 读取视频链接
  - 下载并保存音频
  - Qwen3 语音转文本
  - 提取地点/美食/预算
  - 补充周边可玩地点

#### 核心逻辑

后端通过 `SSE` 返回进度事件。

`SSE` 是服务端事件流，意思是后端不用等全部任务完成，可以一边处理一边把进度推送给前端。

前端通过 `readAnalysisStream` 读取事件，并更新：

| 状态 | 作用 |
|---|---|
| `analysisStageIndex` | 当前进行到第几个阶段 |
| `analysisProgress` | 当前进度百分比 |
| `analysisStatusMessage` | 当前阶段说明 |

#### 前端优化建议

| 优化点 | 说明 |
|---|---|
| 增加取消按钮 | 用户发现等待太久时可以中止 |
| 增加预计耗时 | 长视频时给用户心理预期 |
| 失败保留进度 | 不要失败后直接回首页，可展示失败阶段 |
| 分阶段错误说明 | 比如音频下载失败、ASR 失败、模型分析失败分别提示 |

### 3.3 过渡页：`transition`

入口位置：`TransitionPage`

#### 页面功能

在页面步骤切换之间展示短暂加载状态。

#### 页面内容

- 标题：`正在切换下一步`
- 动态描述：来自 `loadingMessage`
- 固定步骤：
  - 保存当前选择
  - 整理上下文
  - 准备下一个问题

#### 核心逻辑

多个动作会先设置：

```ts
setStep("transition");
```

然后通过 `window.setTimeout` 在约 520ms 后进入目标页面。

#### 前端优化建议

| 优化点 | 说明 |
|---|---|
| 判断是否必要 | 如果没有真实异步任务，这个页面可以改成轻量转场动画 |
| 减少等待感 | 520ms 很短，可用页面淡入淡出代替完整加载页 |
| 与真实任务绑定 | 只有在保存、请求、计算等真实等待时显示 |

### 3.4 视频分析结果确认页：`confirm`

入口位置：`web/app/page.tsx` 中 `if (step === "confirm")`

#### 页面功能

让用户确认系统从抖音视频里识别出的目的地、博主路线、周边推荐，并选择哪些地点要复刻到行程中。

#### 页面内容

- 视频分析摘要
- 状态标签：
  - 是否使用缓存
  - 是否保存音频
  - 是否使用标题兜底分析
- 预算标签
- 美食标签
- 目的地输入框
- 博主路线卡片列表
- 周边推荐卡片列表
- 按钮：
  - `确认地点，进入交通页`
  - `重新输入`

#### 数据来源

该页面使用 `VideoAnalysisResult`：

| 字段 | 说明 |
|---|---|
| `videoId` | 视频 ID |
| `cacheHit` | 是否命中缓存 |
| `title` | 视频标题 |
| `destination` | 识别出的目的地 |
| `summary` | 视频摘要 |
| `transcript` | 音频转写文本 |
| `spots` | 景点列表 |
| `foods` | 美食列表 |
| `budgetText` | 视频中识别出的预算线索 |
| `bloggerPlaces` | 博主路线点 |
| `nearbyPlaces` | 周边推荐点 |
| `needsManualInput` | 是否需要用户手动补充 |

#### 核心逻辑

1. 用户点击地点卡片时，执行 `toggleAnalysisPlace`。
2. 前端维护 `selectedPlaceIds`。
3. 点击确认后执行 `confirmVideoAnalysis`。
4. 将选中的地点写入：
   - `preferences.spots`
   - `preferences.routeReferencePlaces`
5. 将视频预算和美食线索写入 `preferences.notes`。
6. 进入 `transport` 页面。

#### 前端优化建议

| 优化点 | 说明 |
|---|---|
| 强化目的地确认 | 如果目的地识别不稳定，应把输入框放到更突出位置 |
| 点位卡片加图片 | 提升用户对地点的感知 |
| 点位类型图标化 | 景点、美食、街区、住宿用不同图标区分 |
| 选中状态更明显 | 当前用边框和图标，后续可加勾选角标 |
| 增加“全选/清空” | 用户处理多个点位时更高效 |
| 支持手动添加点位 | 识别不完整时用户可主动补充 |

### 3.5 出发城市与交通页：`transport`

入口位置：`web/app/page.tsx` 中 `if (step === "transport")`

#### 页面功能

确认用户从哪里出发，以及希望采用什么大交通方式。

#### 页面内容

- 出发城市输入框
- `GPS 获取` 按钮
- `设为常驻城市` 选项
- `默认驾车出行` 选项
- 暂定出发日期
- 大交通方式选择
- 右侧交通摘要卡片：
  - 路程距离
  - 驾车耗时
  - 驾车花费
  - 火车参考

#### 核心逻辑

进入页面后，如果没有出发城市，前端会尝试自动定位：

1. 读取 `localStorage` 中 24 小时内缓存的常驻城市。
2. 如果没有缓存，则调用浏览器 `navigator.geolocation`。
3. 拿到经纬度后请求 `/api/geo/reverse`。
4. 后端通过高德逆地理编码返回城市。
5. 前端将城市写入 `preferences.origin`。

当出发城市和目的地都存在时，请求：

```text
/api/trips/transport/summary
```

该接口会返回交通摘要信息。

#### 前端优化建议

| 优化点 | 说明 |
|---|---|
| GPS 失败体验 | 明确告诉用户可以手动填写，不要只显示错误 |
| 选项组件更语义化 | `设为常驻城市` 和 `默认驾车出行` 可改成 Switch |
| 交通方式视觉化 | 火车、飞机、自驾可做成分段卡片 |
| 交通摘要骨架屏 | 加载时比文字提示更稳定 |
| 提示数据来源 | 标注“仅供参考，出发前复核” |

### 3.6 偏好向导页：`wizard`

入口位置：`web/app/page.tsx` 中 `if (step === "wizard")`

#### 页面功能

分步收集旅行偏好。

#### 当前实际启用字段

当前 `wizardFields` 只启用了 3 个问题：

| 字段 | 问题 | 控件 |
|---|---|---|
| `days` | 你想玩几天？ | 数字输入框 |
| `budgetStyle` | 这趟更偏哪种预算？ | 下拉选择 |
| `travelInterests` | 这趟旅行你更喜欢什么？ | 标签多选 |

#### 代码中已支持但未放入向导的字段

`renderWizardControl` 中已经支持更多字段：

| 字段 | 说明 |
|---|---|
| `origin` | 出发城市 |
| `transportMode` | 交通方式 |
| `trainSeatPreference` | 火车席别 |
| `hotelPreference` | 酒店偏好 |
| `hotelBudgetPerNight` | 酒店每晚预算 |
| `spotTypes` | 景点类型 |
| `notes` | 补充要求 |

这些字段目前主要集中在 `review` 页面中修改。

#### 核心逻辑

| 状态 | 说明 |
|---|---|
| `fieldIndex` | 当前进行到第几个问题 |
| `currentField` | 当前问题配置 |
| `wizardProgress` | 当前进度，例如 `1 / 3` |

提交时：

1. 执行 `handleWizardSubmit`。
2. 校验当前字段是否有效。
3. 如果不是最后一项，进入下一个问题。
4. 如果是最后一项，进入 `review` 页面。

#### 前端优化建议

| 优化点 | 说明 |
|---|---|
| 统一字段策略 | 要么向导问完整，要么复核页只做确认 |
| 控制多选数量 | 兴趣建议最多 4 个，防止路线生成发散 |
| 增加跳过逻辑 | 可选问题应允许跳过 |
| 表单配置化 | 用统一字段配置驱动控件、校验、默认值 |
| 增强进度感 | 可以展示“还差几步生成方案” |

### 3.7 信息复核页：`review`

入口位置：`web/app/page.tsx` 中 `if (step === "review")`

#### 页面功能

最终确认所有出行信息，并允许用户一次性修改。

#### 页面内容

基础信息：

- 出发城市
- 目的地
- 人数
- 出发日期
- 天数

预算交通：

- 预算风格
- 大交通方式
- 火车席别

住宿：

- 酒店偏好
- 酒店预算/晚

视频线索：

- 复刻路线地点
- 视频识别出的美食
- 视频预算线索

偏好：

- 出行爱好
- 景点类型
- 补充要求

操作：

- `确认并生成方案`
- `返回修改`

#### 核心逻辑

点击生成方案时执行 `startPlanning`：

1. 校验 `canPlan`：
   - 目的地不能为空
   - 出发城市不能为空
   - 天数必须大于 0
2. 重置旧方案、旧事件和旧图片。
3. 设置 `step = "planning"`。
4. 调用 `/api/trips/plan/stream`。

#### 前端优化建议

| 优化点 | 说明 |
|---|---|
| 信息分区 | 当前字段较多，建议分成基础、交通住宿、偏好、视频线索 |
| 视觉降噪 | 次要字段可折叠，比如火车席别、酒店预算 |
| 生成前摘要 | 展示“系统将生成 X 到 Y 的 N 天方案” |
| 明确必填项 | 出发城市、目的地、天数应有必填标识 |
| 日期体验优化 | 返程日期由天数推算，可以直接展示在日期旁 |

### 3.8 Agent 生成中页：`planning`

入口位置：`web/app/page.tsx` 中 `if (step === "planning")`

#### 页面功能

展示 Agent 正在生成旅行方案的过程。

#### 页面内容

- 当前状态说明
- 停止生成按钮
- 出发地、目的地、天数
- 火车席别、日期、人数、酒店偏好、预算
- 实时信息面板
- 逐日方案预览
- 每天生成完成后显示对应 Day 卡片

#### 核心逻辑

前端调用：

```text
/api/trips/plan/stream
```

后端持续返回事件：

| 事件类型 | 说明 |
|---|---|
| `status` | 当前生成状态 |
| `tool` | 工具信息，例如天气、交通、酒店 |
| `summary` | 关键摘要 |
| `day` | 单日行程 |
| `done` | 完整方案完成 |
| `error` | 错误信息 |

前端通过 `readStream` 解析这些事件：

- `summary` 更新 `planSummary`
- `day` 更新 `streamedDays`
- `done` 更新完整 `plan`
- `error` 更新错误提示

#### 前端优化建议

| 优化点 | 说明 |
|---|---|
| 生成状态时间线 | 把工具事件做成清晰时间线 |
| Day 生成状态 | 显示待生成、生成中、已完成 |
| 停止后保留内容 | 停止生成后允许查看已生成的 Day |
| 错误局部化 | 单个工具失败不应影响整体体验 |
| 展示真实数据可信度 | 如“天气已返回”“酒店为搜索兜底” |

### 3.9 最终方案页：`result`

入口位置：`web/app/page.tsx` 最后的默认 `return`

#### 页面功能

展示最终旅行方案，并支持用户继续调整。

#### 页面内容

主内容区：

- 方案标题
- `改信息` 按钮
- Day 标签切换
- 朗读当前计划
- 停止朗读
- 当前 Day 视觉头图
- 时间线点位卡片
- 备选方案展开/收起
- 调整要求输入框

右侧摘要：

- 出发地 -> 目的地
- 天数
- 人数
- 日期
- 预算风格
- 交通方式
- 火车席别
- 兴趣标签
- 总花费估算
- 关键摘要
- 工具记录
- 重新开始按钮

#### 核心逻辑

结果页围绕 `plan` 展示。

关键解析函数：

| 函数 | 作用 |
|---|---|
| `parseDailyPlans` | 把完整 Markdown 方案拆成多个 Day |
| `splitAlternativeSection` | 把每日正文和备选方案拆开 |
| `parseTimelinePoints` | 从每日方案中提取时间线点位 |
| `classifyPoint` | 判断点位类型：景点、美食、交通、住宿、休整 |
| `requestPointImage` | 根据点位请求图片 |

图片逻辑：

1. 景点和酒店优先请求 `/api/places/photo`。
2. 美食图可请求 `/api/images/search`。
3. 如果没有真实图片，使用 `web/public/images/fallback/` 下的兜底图。

朗读逻辑：

1. 用户点击 `朗读当前计划`。
2. 前端调用 `/api/tts`。
3. 后端返回音频。
4. 前端创建 `audioUrl` 并播放。

调整逻辑：

1. 用户输入调整要求。
2. 提交后调用 `/api/trips/refine/stream`。
3. 后端结合旧方案和反馈重新生成。
4. 页面回到 `planning` 状态。

#### 前端优化建议

| 优化点 | 说明 |
|---|---|
| 结构化展示优先 | 不要只依赖 Markdown，时间线和卡片应作为主体验 |
| 点位卡片增强 | 增加预计停留、交通方式、费用、地图入口 |
| 费用拆分 | 当前费用较粗，可拆住宿、餐饮、门票、市内交通 |
| 快捷调整按钮 | 如“降低预算”“增加美食”“少走路”“亲子友好” |
| 移动端优化 | 右侧摘要在移动端应变成顶部摘要或底部抽屉 |
| 方案导出 | 可增加复制、导出 Markdown、分享功能 |

## 4. 通用组件说明

### 4.1 `Shell`

作用：

- 提供统一页面外壳。
- 首页使用 Hero 背景。
- 其他页面使用普通顶部导航。

包含：

- `BrandMark`
- `ProgressNav`
- 页面主体内容

优化建议：

- 移动端压缩顶部高度。
- 进度条与真实步骤状态更精确绑定。

### 4.2 `ProgressNav`

作用：

展示流程进度：

```text
入口 -> 分析 -> 交通 -> 偏好 -> 规划 -> 方案
```

优化建议：

- 当前 `confirm` 属于“分析”，`planning` 属于“规划”，逻辑基本可用。
- 可以增加当前步骤图标。
- 可以在移动端改成更简短的步骤条。

### 4.3 `BrandMark`

作用：

展示产品品牌：

- `DouTrip Agent`
- `DeepAgents itinerary workspace`

优化建议：

- 如果面向真实用户，可以减少技术感副标题。
- 比如改成：`抖音路线复刻助手`。

### 4.4 `ChipGroup`

作用：

用于兴趣和景点类型多选。

优化建议：

- 增加最多选择数量。
- 增加已选择数量提示。
- 多选标签可增加图标。

### 4.5 `LoadingScene`

作用：

用于解析中、过渡中的加载视觉。

优化建议：

- 支持错误状态。
- 支持取消按钮。
- 支持不同阶段的补充说明。

### 4.6 `ToolEventTicker`

作用：

展示 Agent 生成时的实时工具记录。

优化建议：

- 改成时间线结构。
- 对不同事件类型使用不同颜色。
- 区分真实数据、兜底数据、失败数据。

### 4.7 `MarkdownContent`

作用：

统一渲染 Markdown 内容。

使用：

- `react-markdown`
- `remark-gfm`

支持：

- 标题
- 段落
- 列表
- 表格
- 引用
- 行内代码

优化建议：

- 可以为旅行方案定制更明确的排版。
- 比如时间、地点、费用、注意事项分别样式化。

### 4.8 `DayVisualHeader`

作用：

展示单日方案的头图和标题。

优化建议：

- 图片来源可以标注。
- 标题和标签可以增加遮罩适配，防止图片过亮影响阅读。

### 4.9 `TimelinePointGrid`

作用：

展示每日时间线点位卡片。

功能：

- 自动请求点位图片。
- 点击卡片展开详细计划。
- 根据点位类型显示标签。

优化建议：

- 增加地图入口。
- 增加预计费用。
- 增加预计停留时长。
- 增加“加入/移除当前点位”的二次编辑能力。

## 5. 前端与后端接口对应关系

| 前端场景 | 后端接口 | 说明 |
|---|---|---|
| 抖音视频分析 | `POST /api/douyin/analyze/stream` | 流式返回视频分析进度和结果 |
| GPS 反查城市 | `GET /api/geo/reverse` | 经纬度转城市 |
| 交通摘要 | `POST /api/trips/transport/summary` | 查询/估算交通距离、耗时、费用、火车参考 |
| 生成旅行方案 | `POST /api/trips/plan/stream` | 流式生成完整方案 |
| 调整旅行方案 | `POST /api/trips/refine/stream` | 根据反馈重新生成方案 |
| 地点图片 | `GET /api/places/photo` | 高德 POI 图片 |
| 图片搜索 | `GET /api/images/search` | 图片搜索兜底 |
| 朗读方案 | `POST /api/tts` | 文本转语音 |

## 6. 当前前端主要问题

| 问题 | 影响 |
|---|---|
| `page.tsx` 文件过大 | 页面、状态、请求、解析函数混在一起，维护困难 |
| 页面组件未拆分 | 每个 step 的 UI 都堆在同一文件中 |
| 请求逻辑和 UI 耦合 | `fetch`、SSE 解析、状态更新都在页面组件里 |
| `wizard` 和 `review` 字段重复 | 有些字段向导不问，但复核页又能修改 |
| 结果页依赖 Markdown 解析 | 方案结构不稳定时，时间线解析可能不准 |
| 错误状态不够细 | 长任务失败时用户不知道具体失败在哪一步 |
| 移动端摘要体验待优化 | 结果页右侧摘要在移动端需要重新组织 |

## 7. 推荐拆分结构

建议把 `web/app/page.tsx` 拆成页面组件、业务组件、hooks、工具函数。

```text
web/app/page.tsx

web/components/pages/EntryPage.tsx
web/components/pages/ParsingPage.tsx
web/components/pages/ConfirmPage.tsx
web/components/pages/TransportPage.tsx
web/components/pages/WizardPage.tsx
web/components/pages/ReviewPage.tsx
web/components/pages/PlanningPage.tsx
web/components/pages/ResultPage.tsx

web/components/layout/Shell.tsx
web/components/layout/BrandMark.tsx
web/components/layout/ProgressNav.tsx

web/components/trip/DayVisualHeader.tsx
web/components/trip/TimelinePointGrid.tsx
web/components/trip/ToolEventTicker.tsx
web/components/trip/MarkdownContent.tsx
web/components/trip/ChipGroup.tsx
web/components/trip/LoadingScene.tsx

web/hooks/useDouyinAnalysis.ts
web/hooks/useTripPlanning.ts
web/hooks/useOriginCity.ts
web/hooks/usePointImages.ts
web/hooks/useTts.ts

web/lib/trip-types.ts
web/lib/trip-parsers.ts
web/lib/trip-formatters.ts
web/lib/api-client.ts
```

## 8. 推荐优化优先级

### 第一优先级：拆分页面

目标：

- 降低 `page.tsx` 复杂度。
- 每个页面独立维护。
- 后续 UI 优化更安全。

建议先拆：

1. `EntryPage`
2. `ConfirmPage`
3. `TransportPage`
4. `ReviewPage`
5. `PlanningPage`
6. `ResultPage`

### 第二优先级：抽离请求和流式读取

建议抽出：

| Hook | 作用 |
|---|---|
| `useDouyinAnalysis` | 处理抖音视频分析 |
| `useTripPlanning` | 处理方案生成和调整 |
| `useOriginCity` | 处理 GPS、城市缓存和反查 |
| `usePointImages` | 处理点位图片请求和兜底 |
| `useTts` | 处理朗读和停止朗读 |

### 第三优先级：优化核心体验页面

重点页面：

| 页面 | 原因 |
|---|---|
| `confirm` | 用户决定是否相信系统识别结果 |
| `result` | 用户最终消费方案的核心页面 |
| `planning` | 展示 Agent 能力和实时感 |

### 第四优先级：统一表单配置

目标：

- `wizard` 和 `review` 使用同一套字段配置。
- 避免字段重复定义。
- 便于新增偏好问题。

### 第五优先级：增强错误和空状态

需要重点覆盖：

- 抖音链接解析失败
- 音频下载失败
- ASR 失败
- 大模型失败
- GPS 权限失败
- 高德未配置
- 12306 MCP 未配置
- 酒店 MCP 未配置
- TTS 失败

## 9. 页面优化方向汇总

| 页面 | 最重要的优化方向 |
|---|---|
| `entry` | 强化链接输入体验和错误提示 |
| `parsing` | 增加取消、失败阶段说明和等待预期 |
| `confirm` | 强化点位选择体验，支持手动补充 |
| `transport` | 优化 GPS 失败体验和交通方式选择 |
| `wizard` | 统一字段配置，明确问题数量和跳过逻辑 |
| `review` | 信息分区，降低表单密度 |
| `planning` | 强化实时生成过程和 Day 状态 |
| `result` | 结构化展示方案，增强点位卡片和快捷调整 |

## 10. 总结

这个前端已经完成了一个完整 MVP 闭环：

```text
抖音链接输入
  -> 视频分析
  -> 地点确认
  -> 交通确认
  -> 偏好补充
  -> 信息复核
  -> Agent 生成
  -> 结果展示
  -> 反馈调整
```

后续前端优化建议按以下主线推进：

1. 先拆 `page.tsx`，降低维护成本。
2. 再抽离请求、SSE、GPS、TTS、图片等逻辑。
3. 然后重点重做 `confirm` 和 `result` 两个核心体验页面。
4. 最后统一表单配置、增强错误状态和移动端体验。

一句话建议：

**这个前端优化的核心不是先换视觉，而是先把页面边界、状态边界和数据请求边界拆清楚；拆清楚之后，确认页和结果页的体验升级会更稳。**
