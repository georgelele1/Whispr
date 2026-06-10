# Whisper AI-Agent 语音识别、转译与翻译应用

**独立开发｜2026.01 - 2026.04｜Python、SwiftUI、Whisper、LLM Agent、RAG、EventKit**

## 简历精简版

面向跨境企业多语言会议、客户沟通、内部协作和专业文档处理场景，独立设计并实现一套 macOS 原生 AI-Agent 语音转译应用，完成从语音采集、Whisper 转录、意图路由、文本精炼与翻译，到知识检索、日程查询、历史记忆和结果输出的端到端闭环。

- 设计统一 **Agent Loop**，将处理流程拆分为语音转录、文本预清洗、结构化意图识别、Agent 路由、工具执行、结果校验和文本返回，并通过统一数据结构记录 `intent`、工具名称、查询参数、置信度和执行结果。
- 实现“**规则预筛 + LLM 精判**”两层 Intent Router：明确请求通过本地规则快速路由，模糊输入再交由 LLM 输出结构化 JSON，支持 Refiner、Calendar 和 Knowledge 等处理路径，减少不必要的模型调用。
- 构建上下文感知的 **Refiner Agent**，结合目标语言、当前 macOS 应用、用户画像、会话历史、个性化字典和快捷片段动态调整 Prompt，适配邮件、即时通信、文档、终端命令和代码输入等场景。
- 实现轻量级本地 **RAG 与 Knowledge Agent**，支持 TXT、Markdown、JSON、CSV 和 PDF 文档解析、分块、关键词召回、Top-K 排序、文件缓存及上下文预算控制，并基于检索结果生成有来源约束的专业问答。
- 基于 macOS **EventKit** 实现只读 Calendar Agent，支持自然语言日程查询、时间范围解析、系统权限管理和结构化事件返回，并在非 macOS 环境下提供安全降级。
- 设计 **Memory 与个性化字典 Agent**，持久化最近会话和历史转录，自动抽取项目名、人名、缩写及专业术语，通过别名替换和 Prompt 注入提升后续转录中的术语一致性。
- 接入低成本 **Evaluation Pipeline**，默认使用本地规则完成空输出、长度、格式和填充词检查，并支持通过环境开关启用 LLM Judge，避免在正常请求中增加额外模型调用。
- 使用 SwiftUI 开发 macOS 菜单栏应用、悬浮录音 HUD、全局快捷键、语言与模型选择、历史记录、术语字典和 Snippets 管理界面；通过 Swift `Process` 与 Python CLI 完成进程通信和 JSON 数据传输。
- 完成后端单元测试、结构化输出校验、异常降级和本地运行环境打包；针对语义片段匹配、外部模型超时和日历权限异常设计容错逻辑，避免辅助模块故障中断主转录流程。

## 核心设计详述

### 1. Agent Harness 与执行框架

围绕语音输入后的任务处理建立统一执行框架，将不同能力拆分为独立模块：

```text
Audio Input
    -> Whisper Transcription
    -> Local Text Cleaning
    -> Intent Router
    -> Agent / Tool Execution
    -> Output Evaluation
    -> History & Memory Update
    -> Final Text
```

主流程以结构化路由对象传递任务信息，包含：

- `intent`
- `need_tool`
- `tool_name`
- `query`
- `start_iso` / `end_iso`
- `confidence`
- `reason`

该设计将路由决策、工具执行和文本生成解耦，使后续新增邮件检索、CRM、文档问答等 Agent 时无需重写语音转录主流程。

### 2. LLM Agent Loop

Agent Loop 采用“本地快速处理优先、LLM 处理复杂语义”的执行策略：

1. Whisper 将录音转换为原始文本。
2. 本地规则清除填充词、重复词并应用个性化术语替换。
3. Intent Router 判断任务类型和工具需求。
4. Calendar 或 Knowledge 请求进入专用 Agent，其余请求进入 Refiner Agent。
5. Evaluation Pipeline 对输出执行低成本校验。
6. 最终结果写入 Session、History 和个性化学习数据源。

对于普通润色、翻译、邮件、聊天、代码和会议内容，不额外拆分多个生成 Agent，而是由 Refiner 根据应用上下文和用户意图动态调整输出格式，从而控制系统复杂度和模型调用成本。

### 3. Intent Router 与工具调度

实现两层路由机制：

- **规则层**：识别“查看明天日程”“检索专业文献”等高确定性表达，直接生成路由结果。
- **LLM 层**：处理语义模糊的输入，要求模型返回严格 JSON，并在解析失败或置信度不足时自动回退到 Refiner。

当前主要路由包括：

| Intent | 执行模块 | 说明 |
|---|---|---|
| `refine` | Refiner Agent | 润色、翻译、邮件、聊天、代码及普通文本 |
| `calendar` | Calendar Agent | 查询 macOS 本地日历事件 |
| `knowledge` | Knowledge Agent | 检索本地专业文档并生成回答 |

Snippets 模块采用本地精确匹配优先，仅在未命中时调用语义匹配模型；语义请求超时后自动降级为无匹配，不影响主流程。

### 4. RAG 与 Knowledge Agent

采用适合本地桌面应用的轻量 RAG 方案，避免引入独立向量数据库和常驻服务：

- 扫描用户知识目录和应用内置知识目录。
- 解析 TXT、Markdown、JSON、CSV 和文本型 PDF。
- 按固定长度和自然段边界进行重叠分块。
- 对中英文内容进行关键词与中文 Bigram 标记化。
- 计算查询与文档块的归一化词项重合度。
- 返回 Top-K 相关片段并限制 Prompt 上下文总长度。
- 根据文件修改时间缓存解析结果，文件未变化时不重复读取和分块。

Knowledge Agent 被约束为仅根据召回内容回答，在证据不足时明确说明，并保留来源文件名，降低专业内容生成中的幻觉风险。

### 5. Calendar Agent

Calendar Agent 使用 EventKit 读取 macOS 系统日历：

- 支持今天、明天及指定时间区间的自然语言解析。
- 处理 Full Access 权限申请、拒绝和超时。
- 返回标题、开始时间、结束时间、全天事件、日历名称、地点和备注。
- 默认只读，不执行事件创建或修改，降低误操作风险。
- 在 Windows 或 EventKit 不可用时返回明确错误，不影响其他 Agent。

### 6. Memory、Profile Learning 与个性化字典

系统包含三类互补的上下文能力：

- **Session Memory**：保存最近三轮交互，并设置 60 分钟过期时间，用于处理“更简短一些”“翻译上一段”等跟进指令。
- **Profile Learning**：根据历史数量和最后处理时间戳，每新增约 50 条记录触发一次后台分析，提取写作风格、常见主题和高频应用；学习任务使用独立进程执行，不阻塞当前转录。
- **Dictionary Agent**：从历史转录中提取专业术语、项目名、人名和缩写，保存正确写法及可能的误识别别名，并在后续文本处理前执行本地替换。

Profile Learning 使用持久化时间戳而非进程内计数，解决 Python CLI 每次启动新进程以及历史记录达到容量上限后无法继续学习的问题。

### 7. Evaluation Pipeline

Evaluation Pipeline 以低延迟为优先：

- 默认执行本地确定性检查，不产生额外 Token。
- 检查空输出、异常长度、残留填充词和基础格式。
- 将 `verdict`、`reason` 和评估方式写入结构化结果及历史记录。
- 调试环境可通过 `WHISPR_DEBUG_EVAL=1` 启用一次 LLM Judge。
- Router JSON 解析失败、低置信度或工具异常时均提供回退路径。

相比每次执行多轮 LLM 自我反思，该设计保留基本质量控制能力，同时控制端到端响应时间和 API 成本。

### 8. macOS 前端与本地部署

SwiftUI 前端包含：

- 菜单栏控制器
- 悬浮录音与处理状态 HUD
- 全局快捷键监听
- AVFoundation 音频录制
- 当前应用检测与文本自动粘贴
- 输出语言和模型选择
- 历史记录检索
- 个性化字典管理
- Voice Snippets 管理
- 首次启动和运行环境初始化

前端通过 `Process` 启动本地 Python CLI，将音频路径、当前应用和目标语言传入后端，并通过 JSON 接收最终文本、路由信息和评估结果。用户数据、历史、字典和知识文档均保存在本地 Application Support 目录。

## 面试表述建议

### 项目亮点

- 不是简单调用 Whisper 和 LLM，而是围绕语音输入构建了完整的路由、工具、记忆、检索和质量控制流程。
- 通过规则优先、缓存、Top-K、上下文预算和后台学习控制模型调用次数与响应延迟。
- 将 macOS 原生能力与 Python Agent 后端结合，完成可交互、可部署的桌面产品原型。
- 对模型超时、权限拒绝、JSON 解析失败、知识不足和辅助 Agent 异常均设计了降级路径。

### 指标使用说明

除非已经完成正式基准测试，否则不建议在简历中直接写“效率提升 30%”或“准确率提升 25%”。可以替换为：

- “减少高确定性任务中的不必要 LLM 调用”
- “提升专业术语在连续使用过程中的一致性”
- “通过本地规则校验和异常回退提升系统稳定性”
- “通过缓存和上下文预算降低重复解析与 Token 消耗”
