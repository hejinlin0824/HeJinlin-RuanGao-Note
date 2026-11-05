# TP-06 目录结构识别与人工修正验收

## 1. 目标与边界

TP-06 只识别教材本身的章内目录结构，不抽取知识点，也不生成知识关系。

目录候选必须来自 heading 类型的 SourceBlock；系统不会把普通段落转换成 Section。每个自动生成的目录节点通过 sections.source_block_id 外键回连标题证据块，并可进一步定位 ChapterPage 原图。

当前版本使用确定性编号与上下文规则，不调用大模型。对于无编号标题、缺失父级或层级跳跃，保留节点并创建 AuditIssue，交由人工确认。

## 2. 数据库变更

新增 Alembic 迁移：0004_section_source_block。

- sections.source_block_id：可空外键，引用 source_blocks.id，删除策略为 RESTRICT。
- 已有目录数据不需要回填；新生成的目录节点都会关联标题 SourceBlock。
- 人工修正记录追加写入 audit_events，不覆盖历史记录。

## 3. 自动识别规则

| 标题形式 | 处理规则 |
|---|---|
| 第1章 信息化发展 | 与 Chapter 标题相同或符合章节总标题形式时跳过，避免重复一层 |
| 1.1 信息与信息化 | 作为章内第 1 层目录 |
| 1.1.1 信息 | 作为 1.1 的第 2 层子目录 |
| 1.1.1.1 ... | 作为更深一层目录 |
| 1. 信息的定义、2. 信息的特征 | 结合最近的明确编号标题推断子级；有歧义时生成审核问题 |
| 无编号标题 | 按上下文暂定层级，同时生成 unclassified_heading_level |

校验包括重复标题、重复编号、缺失父级、层级跳跃、编号不连续和空标题文本。校验只生成审核问题，不删除标题块或目录节点。

重复点击“识别 / 补全目录”是幂等的：已绑定 SourceBlock 的 Section 不会重复创建，人工修改过的 title/parent/level/sort_order 不会被自动识别覆盖。

## 4. 前端验收

更新 dev 分支，安装开发依赖，并启动本地服务：

- git switch dev
- git pull --ff-only origin dev
- python -m pip install -e ".[dev]"
- uvicorn ruangao_note.main:app --app-dir backend --reload --host 127.0.0.1 --port 8765

打开 http://127.0.0.1:8765/outline-review

操作：

1. 选择已经完成 TP-05 的教材和章节。
2. 点击“识别 / 补全目录”。
3. 检查目录树中的编号、层级和父子关系。
4. 点击“查看教材原页”，确认标题节点跳转到正确的教材页面。
5. 修改一个标题名称、父级或排序并保存。
6. 刷新页面，确认修改仍然存在。
7. 查看“结构检查”和“目录修改记录”，确认问题和操作历史可见。
8. 再次点击“识别 / 补全目录”，确认不会重复创建或覆盖人工修改。

## 5. API 合同

- POST /api/chapters/{chapter_id}/sections/generate：幂等生成/补全目录。
- GET /api/chapters/{chapter_id}/sections：返回目录节点、来源页链接、未解决审核问题和最近 100 条修改记录。
- PATCH /api/chapters/{chapter_id}/sections/{section_id}：人工修改 title、section_number、level、parent_id、sort_order；写入 AuditEvent。

手工修改不能把父级设为自己或后代；父级必须属于同一章节，子节点层级必须大于父节点层级。

## 6. 自动化测试范围

- 编号目录树与父子关系。
- 单级数字标题按上下文归属。
- 缺失父级节点保留并生成 AuditIssue。
- 重复识别幂等。
- 人工修改有 before/after 审计记录。
- 拒绝父子循环。
- HTTP API 的生成、查询、修改和原文链接。
- Alembic 从空库迁移到最新版本。
