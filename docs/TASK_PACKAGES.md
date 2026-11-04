# 任务包与实施路线图

- 对应 Spec：v0.2
- Python 基线：3.13.15
- 当前阶段：TP-00～TP-03 已完成验收；TP-04 已包含 Mock OCR、MinerU v4 云端章节批量解析、隐藏式本地 Token 配置和章节 PDF 组装测试；GitHub Actions 已通过（35 passed），等待 Windows 本地与真实云端验收。
- 实施原则：一次推进一个任务包；完成后运行测试、检查差异、记录结果，再进入下一个任务包。

## 1. 总体实施策略

不按“先做完所有 AI 功能，再做界面”的方式开发。采用纵向切片：先搭建可运行骨架，再打通最小导入链路，然后逐步增加结构化、可视化、审核和复习。

首个可交付目标不是全功能平台，而是：

**用户能上传一章教材图片 → 得到带来源锚点的 Markdown → 查看章节/知识点结构 → 从知识点回到原图原文。**

在这个闭环稳定后，再扩展全书架构、图表重建、题库和复习。

## 2. 任务包总览

| 顺序 | 任务包 | 目标 | 依赖 | 优先级 |
|---|---|---|---|---|
| 00 | 项目规范与工程约定 | Spec、任务包、开发约定落盘 | 无 | P0 |
| 01 | Python 环境与项目骨架 | 3.13.15 可安装、可启动、可测试 | 00 | P0 |
| 02 | 领域模型与数据库 | 建立教材、章节、页面、来源块等基础模型 | 01 | P0 |
| 03 | 图片导入与页面管理 | 上传、排序、替换、原图存储 | 02 | P0 |
| 04 | OCR Provider 与预处理 | 图像质量检查、OCR 接口、结果持久化 | 03 | P0 |
| 05 | SourceBlock 与 Markdown | 块切分、稳定锚点、章节 Markdown | 04 | P0 |
| 06 | 目录结构识别与人工修正 | 章/节/小节树及校验 | 05 | P0 |
| 07 | 知识点抽取与来源绑定 | 知识树、知识来源多对多关联 | 06 | P0 |
| 08 | 章节架构视图 | 本章目录、主线、提要、知识关系 | 07 | P1 |
| 09 | 知识点架构视图 | 知识图谱、关系过滤、原文跳转 | 07 | P1 |
| 10 | 全书架构视图 | 全书目录、主题板块、章节关系和覆盖度 | 08、09 | P1 |
| 11 | 图表识别与 Mermaid 回退 | 图片分类、重建、渲染、原图回退 | 05 | P1 |
| 12 | 审核工作台 | OCR、目录、知识、关系、图表审核 | 05、06、07、11 | P1 |
| 13 | 题目生成与审核 | 填空、选择、简答题及质量检查 | 07、12 | P1 |
| 14 | 答题与复习调度 | 答题记录、错题队列、掌握状态 | 13 | P1 |
| 15 | 导出、备份与端到端验收 | Markdown/JSON 导出、备份恢复、整体验收 | 10、12、14 | P1 |
| 16 | 体验优化与稳定性 | 性能、可访问性、错误恢复、文档完善 | 15 | P2 |

建议不要并行开发相互依赖的任务包。可以并行做独立调研，但代码合并和验收按顺序推进。

## 3. 每个任务包的交付定义

### TP-00：项目规范与工程约定（当前完成）

交付：
- README.md
- docs/PROJECT_SPEC.md
- docs/TASK_PACKAGES.md

验收：
- 项目目标、三层架构、数据原则、范围、里程碑和验收标准明确。
- 任务包有顺序、依赖和完成定义。
- Python 基线明确为 3.13.15。

状态：文档已写入仓库；后续随着实施更新状态。

### TP-01：Python 环境与项目骨架

目标：建立可在 Windows + Python 3.13.15 下稳定运行的最小项目。

建议结构：
- backend/app/main.py
- backend/app/core/config.py
- backend/app/api/
- backend/app/domain/
- backend/app/services/
- backend/tests/
- frontend/（前端技术选型确认后初始化）
- pyproject.toml
- .python-version
- .env.example
- .gitignore

工作项：
1. 检查 Python 3.13.15 环境。
2. 建立 pyproject.toml 和开发依赖。
3. 配置 FastAPI、Pydantic、SQLAlchemy、Alembic、pytest。
4. 提供健康检查接口。
5. 统一配置读取和日志格式。
6. 提供本地启动说明。
7. 建立最小 CI：安装、lint（可后置）、pytest。

验收：
- 全新虚拟环境可安装。
- python --version 输出 3.13.15。
- 服务能启动，健康检查返回成功。
- pytest 可运行。
- 不提交 .env、API Key、用户教材图片或数据库文件。

### TP-02：领域模型与数据库

目标：先确定数据边界，避免后续把目录、知识点和原文块混为一张表。

工作项：
1. 建立 Book、Chapter、Section、ChapterPage。
2. 建立 ProcessingRun、SourceBlock。
3. 建立 KnowledgeNode、KnowledgeSource。
4. 建立 Relation、RelationEvidence、Figure、AuditIssue、AuditEvent。
5. 建立 Question、QuestionSource、ReviewState、AnswerLog 的初始模型或预留迁移。
6. 配置 SQLAlchemy 关系、约束和 Alembic 初始迁移。
7. 建立 Repository/Service 层，避免 API 直接操作复杂 SQL。

验收：
- 数据库可从空库迁移到最新版本。
- 外键和唯一约束有效。
- KnowledgeNode 与 SourceBlock 是多对多。
- 目录层级和知识点层级独立。
- 关系边具有类型、方向、证据引用和审核状态。
- 有模型 CRUD 和迁移测试。

### TP-03：图片导入与页面管理

状态：自动化测试与 Windows 本地验收通过（22 passed）；TP-03 已完成。

目标：可靠保存原始教材页面，并支持顺序管理。

工作项：
1. 创建教材和章节 API。
2. 多图片上传，限制类型和大小。
3. 原图写入本地对象目录，数据库只记录相对路径。
4. 生成 SHA-256，识别重复文件。
5. 支持页序调整、教材页码编辑、删除和替换。
6. 支持图片预览和基础元数据读取。
7. 文件操作失败时清理孤立临时文件，不破坏已保存文件。

验收：
- 20+ 张图片可上传。
- 页序调整后持久化正确。
- 替换图片不覆盖历史原图。
- 文件哈希、尺寸、页码记录正确。
- 不允许路径穿越和任意文件读取。
- 图片重启后仍可读取。

### TP-04：OCR Provider 与图像预处理

目标：把 OCR 能力封装为可替换服务，不让业务层依赖某一家模型。

工作项：
1. 定义 OCRProvider 协议和标准输出 Schema。
2. 定义预处理接口：方向、裁边、去噪、透视校正、质量评估。
3. 每页建立 ProcessingRun 和状态。
4. OCR 结果保存为原始响应和标准化结果。
5. 对低分辨率、模糊、倾斜、空白页生成质量问题。
6. 支持单页重试、失败状态和错误详情。
7. 设计 Mock Provider，保证不配置 API Key 也能跑通测试。

验收：
- 可替换 OCR Provider，不修改核心业务服务。
- 单页失败不影响其他页面。
- 原始 OCR 响应可追溯。
- Python 3.13.15 下图像依赖安装通过。
- 测试覆盖正常、超时、异常、低质量图片。

### TP-05：SourceBlock 与 Markdown

目标：建立整套系统最重要的证据层。

工作项：
1. 将 OCR/版面结果切分为标题、段落、表格、图注、公式、脚注、代码块等。
2. 为每个块分配稳定 ID、页码、bbox、类型和置信度。
3. 生成 Markdown，并在块附近写入来源锚点。
4. 保存 Markdown 与生成版本，支持重新生成。
5. 脚注独立保存，正文保留引用标记。
6. 页眉页脚、水印和重复文本分类，不直接混入正文。
7. 提供从 block_id 到页面图片和 bbox 的定位接口。

验收：
- Markdown 每个主要内容块均可追溯。
- 锚点在同一处理版本内稳定。
- 新 OCR 版本不静默破坏旧锚点。
- 脚注、页眉、水印不会无条件拼入正文。
- 表格/公式无法可靠识别时保留原图或原始区域。
- 有端到端测试样例和人工检查报告。

### TP-06：目录结构识别与人工修正

目标：识别教材本身的章节结构，不把知识点抽取混进目录识别。

工作项：
1. 从标题编号、字体/版面和上下文识别章、节、小节。
2. 生成 Section 树和排序。
3. 规则校验编号连续性、层级跳跃、空节点、重复标题。
4. 支持人工改标题、改层级、拖拽排序。
5. 将标题节点关联到对应 SourceBlock。
6. 保留 AI 候选和人工修正记录。

验收：
- 能展示章/节/小节目录树。
- 结构错误会生成 audit issue。
- 用户修改后目录持久化。
- 每个标题节点可定位原文。
- 不因编号不规则就丢弃标题。

### TP-07：知识点抽取与来源绑定

目标：从原文块中生成可审核的知识点树。

工作项：
1. 定义 KnowledgeNode 标准 Schema。
2. 生成知识点候选：概念、定义、组成、步骤、条件、方法、优缺点等。
3. 绑定 source_refs，落入 KnowledgeSource 多对多表。
4. 建立知识点父子关系，但不把一般关系强塞进 parent_id。
5. 检查重复节点、空节点、来源不存在、来源内容不支持摘要。
6. 状态区分 draft、needs_review、approved、rejected。
7. 提供人工合并、拆分、改名和来源增删能力。

验收：
- 所有候选节点可定位原文。
- 无来源节点不能批准。
- 知识点父子关系与关系图边分离。
- 可人工修正并留痕。
- 80% 候选来源绑定率作为首轮目标；批准节点来源绑定率 100%。

### TP-08：章节架构视图

目标：把一章的内容组织成可理解的宏观结构。

工作项：
1. 章节一句话提要和学习目标。
2. 章/节/小节树形视图。
3. 按教材顺序组织的知识主线。
4. 核心知识点和易混点。
5. 本章关系图候选。
6. 每项摘要和节点都能跳转来源。
7. 区分原文事实、忠实归纳和 AI 辅助讲解。

验收：
- 用户能从章节页理解本章结构。
- 点击任意知识点进入知识详情。
- 章节提要的事实性陈述均有来源。
- AI 推测内容不混入正式事实。

### TP-09：知识点架构视图

目标：让用户看清知识点之间的组成、前置、对比、流程和应用关系。

工作项：
1. 实现关系类型枚举和方向约束。
2. 生成关系候选并绑定 evidence_refs。
3. 提供关系图、树形图和对比视图。
4. 支持关系类型过滤、节点搜索、展开/折叠。
5. 节点详情展示定义、要点、摘要、讲解和来源。
6. 原文块反向列出引用它的知识点和题目。
7. 低置信度/待审核边默认隐藏或弱化显示。

验收：
- 关系边两端存在。
- 正式关系边 100% 有证据。
- 因果、前置、一般关联不混淆。
- 节点可一键跳转原文。
- 提供列表视图作为图形视图的替代。

### TP-10：全书架构视图

目标：从单章扩展到整本书的宏观组织。

工作项：
1. 展示全书目录树。
2. 展示各章导入、OCR、审核、结构化进度。
3. 从已审核知识点聚合主题候选。
4. 建立章节 × 主题矩阵。
5. 建立章节关系候选：目录顺序、教材引用、前置建议、主题关联。
6. 章节关系显示证据和关系来源类型。
7. 点击章节进入章节架构；未导入章节只显示目录占位。

验收：
- 全书结构一目了然。
- 未导入章节不会出现虚构知识点。
- 每个主题能追溯到章节/知识点。
- AI 推测的章节关系与教材明确关系视觉区分。
- 可以按主题和章节筛选。

### TP-11：图表识别与 Mermaid 回退

目标：提升图表可读性，但不牺牲原始证据。

工作项：
1. 图像块分类。
2. 为适合的图生成 Mermaid 草稿。
3. Mermaid 语法校验和实际渲染。
4. 保存原图、源码、渲染状态和失败原因。
5. 提供原图/Mermaid 切换。
6. 记录提取的节点/边清单供人工核对。

验收：
- Mermaid 渲染成功才显示重建图。
- 失败自动显示原图。
- 不适合重建的图片直接保留原图。
- 图表任务失败不影响正文处理。

### TP-12：审核工作台

目标：让模型生成内容可控、可查、可纠错。

工作项：
1. 汇总 OCR 低置信度、目录冲突、无来源节点、关系证据缺失、图表失败、题目质量问题。
2. 支持批准、修改后批准、驳回、暂缓。
3. 支持从审核项打开原图和原文块。
4. 保存审核前后内容、操作人、时间和原因。
5. 审核状态改变后刷新相关图谱/题库视图。

验收：
- 未批准内容不会进入正式学习视图。
- 每项审核问题可定位来源。
- 审核历史不可被静默覆盖。
- 审核状态变化有自动化测试。

### TP-13：题目生成与审核

目标：生成有用且可追溯的自测题。

工作项：
1. 填空题候选生成和答案抽取。
2. 单选题生成、干扰项构造和唯一正确项校验。
3. 简答题生成标准答案和要点清单。
4. 每题绑定 knowledge_id 和 source_refs。
5. 检查停用词、歧义、答案不在来源、重复题和选项同义。
6. 提供题目人工审核、修改和驳回。
7. 记录生成模型和提示版本。

验收：
- 每题都有来源。
- 选择题只有一个正确选项。
- 简答题显示标准答案、要点和来源。
- 未审核题不进入复习队列。
- 题目质量问题有可读的审核原因。

### TP-14：答题与复习调度

目标：实现从测试到长期复习的闭环。

工作项：
1. 题目作答和答案展示。
2. 简答题会/不会自评。
3. 保存 AnswerLog。
4. 按知识点和题目分别维护 ReviewState。
5. 实现 1、2、4、7、15、30 天间隔规则。
6. 连续 5 次正确标记掌握。
7. 掌握后答错撤销掌握并缩短间隔。
8. 今日待复习列表和错题回看。

验收：
- 所有状态转换有单元测试。
- 答题记录可追溯到题目和原文。
- 简答自评参与复习计算。
- 掌握后答错会重新进入复习队列。
- 日期边界和时区处理正确。

### TP-15：导出、备份与端到端验收

目标：保证用户的数据可带走、可恢复，并验证真实学习闭环。

工作项：
1. 导出章节 Markdown 和来源清单。
2. 导出题库 JSON。
3. 备份数据库和图片文件。
4. 提供恢复流程和校验。
5. 用真实 20+ 页教材完成端到端测试。
6. 整理验收报告、性能记录和已知限制。

验收：
- 导出文件可独立读取。
- 备份恢复后图片、锚点、知识点、题目关系完整。
- 从上传到复习的主链路通过。
- 不存在无来源的正式知识或题目。

### TP-16：体验优化与稳定性

工作项：
- 图谱大数据量渲染优化。
- 上传进度、任务状态和失败重试体验。
- 键盘操作、窄屏布局和无障碍检查。
- 错误提示和日志完善。
- 安全检查、依赖更新和文档整理。

验收：
- 核心页面在常见桌面浏览器可用。
- 长任务不会阻塞交互。
- 错误状态可理解、可恢复。
- 回归测试通过。

## 4. 每个任务包的统一交付模板

每个任务包完成时，必须提交：
1. 目标与范围（本次做什么、不做什么）。
2. 变更文件清单。
3. 关键设计说明。
4. 自动化测试命令和结果。
5. 手动验收步骤与预期结果。
6. 已知问题和后续任务。
7. 更新本文件中的任务状态。

禁止只报告“已完成”而没有测试证据。

## 5. 当前执行状态

| 任务包 | 状态 | 说明 |
|---|---|---|
| TP-00 | 文档已落盘 | README、Spec、任务包路线图 |
| TP-01 | 已完成 | Python 3.13.15、Ruff、pytest、FastAPI 启动和健康检查已验收 |
| TP-02 | 已完成 | 领域模型、SQLite、Alembic、Repository/Service 和迁移测试已验收 |
| TP-03 | 已完成 | 图片上传、原图存储、页面生命周期 API；GitHub CI 与 Windows 本地验收均通过，22 passed |
| TP-04 | GitHub CI 通过，待 Windows/真实云端验收 | 单页 Mock OCR 保留；新增章节图片按序合并 PDF、MinerU v4 batch 上传/轮询/ZIP 解析、Token 本地隐藏配置与章节级 ProcessingRun。SourceBlock 映射属于 TP-05 |
| TP-05～TP-16 | 待开始 | 按依赖顺序推进 |

## 6. TP-01 当前实现记录

已在 dev 分支建立：
- .python-version（3.13.15）和 pyproject.toml（要求 Python >=3.13,<3.14）。
- FastAPI 应用入口、/health/live 与 /health/ready。
- 基于环境变量的 Pydantic Settings。
- pytest 健康检查与配置测试。
- Ruff 配置、GitHub Actions Python CI、.gitignore 和 .env.example。

待完成验收：在实际 Python 3.13.15 环境执行 pip install -e ".[dev]"、ruff check .、pytest，并确认 GitHub Actions 成功。未获得运行结果前，不将 TP-01 标记为完成。

## 7. 第一轮具体执行顺序

1. TP-01：完成本地/CI 验收，确认 Python 3.13.15、依赖兼容性和最小启动。
2. TP-02：确定领域模型与数据库迁移。
3. TP-03：打通图片上传和页面管理。
4. TP-04：接入 OCR Provider 和图像预处理。
5. TP-05：建立 SourceBlock 与 Markdown 锚点。
6. 之后再进入目录识别、知识点、三层架构视图。

每一轮只推进当前任务包。若发现 Spec 中有设计缺口，先记录并更新文档，再实现，不要临时堆代码。


## 8. TP-02 当前实现记录（待本地验收）

### 已提交到 dev 的实现

- 数据库基础设施：SQLAlchemy 2.x Declarative Base、UTC 时间戳、SQLite 文件目录创建、SQLite 外键约束启用、进程级 Engine/SessionFactory 和请求级 Session 生成器。
- 教材目录与页面：Book、Chapter、Section、ChapterPage。
- 处理与证据：ProcessingRun、SourceBlock。
- 知识结构：KnowledgeNode、KnowledgeSource（知识点与原文块多对多）。
- 关系与审核：Relation、RelationEvidence、Figure、AuditIssue、AuditEvent。
- 题库与复习预留：Question、QuestionSource、ReviewState、AnswerLog。
- 初始 Repository/Service：BookRepository、BookService。
- Alembic 配置与初始迁移：alembic.ini、backend/alembic。
- readiness 接口现在执行数据库 SELECT 1；数据库不可用时返回 HTTP 503。
- 自动化测试覆盖表结构、知识点—原文多对多、关系—原文证据关联、目录树与知识树分离、关系端点约束、SQLite 外键和 BookService。

### 关键建模约束

1. Section.parent_id 只表达教材目录树；KnowledgeNode.parent_id 只表达知识点学习层级，二者完全独立。
2. KnowledgeSource 是独立关联表，一个知识点可引用多个 SourceBlock，一个 SourceBlock 也可被多个知识点引用。
3. Relation 的端点必须是完整的“知识点—知识点”或“章节—章节”组合，不能混用；关系方向、类型、来源和审核状态独立保存。RelationEvidence 通过外键关联真实 SourceBlock，避免把无法校验的来源 ID 塞进自由文本。
4. SourceBlock 必须关联 ChapterPage 和 ProcessingRun，原文证据带有处理版本。
5. ReviewState/AnswerLog 通过 target_type + target_id 支持知识点或题目两种复习粒度；这两处是有意采用的多态引用，后续服务层必须验证目标存在。

### 初始迁移说明

当前 0001 初始迁移通过当时的 SQLAlchemy metadata 创建初始空库，目的是先建立可运行的初始 schema。它只用于全新数据库初始化；后续结构变更必须使用显式 Alembic operations 生成不可变迁移，不能修改已发布迁移来“追平”模型。

### 本地验收命令

在项目根目录、Python 3.13.15 虚拟环境中执行：

```powershell
ruff check .
pytest -v
alembic upgrade head
alembic current
```

再验证数据库文件生成后，启动服务：

```powershell
uvicorn ruangao_note.main:app --app-dir backend --reload --host 127.0.0.1 --port 8765
```

访问 `/health/ready` 应返回 `{"status":"ready"}`。首次迁移后可通过 `alembic current` 确认版本为 `0001_initial_domain`。

TP-02 在以上命令真实运行并修复问题前，不标记为完成。


## 9. TP-04 首版实现记录（CI 通过，等待 Windows 验收）

### 已实现

- `ProcessingRun` 新增 `normalized_result` 与 `quality_report` JSON 字段，使用 `0003_ocr_results` 独立迁移；保留 `raw_result` 原始响应。
- `OCRProvider` Protocol 规定统一识别方法；`OCRProviderResponse` 与 `OCRBlock` 作为 Provider 无关的标准化输入。
- `normalize_response` 校验置信度范围、bbox 归一化范围与坐标方向，统一文本块 ID、类型、顺序和字段。
- `MockOCRProvider` 不调用外部服务、不生成虚构文本，明确在原始响应中标记 `simulated=true`。
- `preprocess_image` 在内存中执行 EXIF 方向校正、页面旋转、灰度、自动对比度和质量启发式检查；不覆盖原图、不保存未经请求的派生文件。
- `OCRService` 每次调用新建 ProcessingRun，记录 queued/running/succeeded/failed 生命周期、原始响应、标准化结果、质量指标和异常。
- API：`POST /api/chapters/{chapter_id}/pages/{page_id}/ocr`；`GET /api/chapters/{chapter_id}/pages/{page_id}/ocr-runs`。

### 当前限制

- OCR 执行是同步请求内处理，尚未接入后台队列；长耗时云 OCR 不应直接沿用同步执行方式。
- Mock Provider 只验证接口和持久化链路，真实识别能力需要后续独立 Provider 实现。
- 当前质量指标为启发式提示，不等同于专业图像质量评估；倾斜角检测、裁边、透视矫正尚未实现。
- 当前结果尚未自动写入 SourceBlock；该职责属于 TP-05，避免 OCR 任务和证据块生成耦合。


## 10. TP-04 MinerU 云端章节批处理补充

- 参考项目：`hejinlin0824/HeJinlin-paperLib/backend/app/services/parser_mineru.py`，复用其 MinerU v4 流程：申请批量上传 URL、预签名 PUT、轮询 batch、下载 ZIP。
- 章节接口：`POST /api/chapters/{chapter_id}/ocr`。仅选择 `status=stored` 的活动页面，按 `sort_order` 排序，构建一个多页 PDF 并创建一个 MinerU batch 任务。
- PDF 仅作为临时内存派生文件；EXIF 方向和页面旋转会应用到 PDF 页面，单页最大边长限制为 3508 像素，原图与 SHA-256 不变。
- MinerU 结果中的 Markdown、JSON 和文件清单保存到章节级 ProcessingRun；每个 PDF 页码与 ChapterPage ID 的映射同时保存。TP-05 再把布局块映射成稳定 SourceBlock。
- Token 仅从本机项目根目录 `.env` 读取；`scripts/configure_mineru.ps1` 使用隐藏输入写入该文件。真实凭据不得进入仓库、数据库或日志。
- 预签名上传 URL 和结果 ZIP URL 均不携带 Bearer Token；ZIP 路径穿越会被拒绝。
- 当前实现仍是同步长请求，默认最多轮询 25 分钟；任务队列、回调、断点恢复与自动 SourceBlock 生成尚未实现。
