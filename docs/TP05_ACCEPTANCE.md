# TP-05 原文证据块与 Markdown 验收

## 1. 环境与自动化检查

在项目根目录、Python 3.13.15 虚拟环境中执行：

```powershell
git switch dev
git pull origin dev
python -m pip install -e ".[dev]"
.`test.bat`
```

也可分别执行：

```powershell
ruff check .
pytest -v
```

## 2. 数据原则

- `ProcessingRun.raw_result` 和 `normalized_result.artifacts` 保存 MinerU 原始输出，不因清洗而覆盖。
- SourceBlock 必须通过 MinerU `page_idx` → PDF 页码 → TP-04 `page_references` → ChapterPage ID 形成明确映射。
- MinerU 页码按 0-based `page_idx` 解释；TP-04 PDF 页码按 1-based `pdf_page_index` 保存。
- 没有页级布局证据时不猜测页归属。
- 水印、页眉页脚和脚注检测目前只生成候选，不删除 SourceBlock 或原始 OCR 文本。

## 3. API 验收

先完成 TP-04：创建教材、章节、上传页面并运行章节 MinerU OCR。取得成功的 `chapter_id` 与 `run_id`。

### 3.1 物化原文块

调用：

```http
POST /api/chapters/{chapter_id}/ocr-runs/{run_id}/source-blocks
```

预期返回：

- `count`：创建或复用的 SourceBlock 数量。
- `items`：每块的 block_key、类型、文本、bbox、page_id、content_hash。
- `report.cleanup_candidates`：疑似水印、脚注、重复短文本候选。
- `anchored_markdown`：包含 `<!-- source:block_key -->` 的 Markdown。

重复调用该接口不应重复创建记录。

### 3.2 查询原文块

调用：

```http
GET /api/chapters/{chapter_id}/ocr-runs/{run_id}/source-blocks
```

预期每个块都包含 `page_id` 和 `image_url`，可追溯到 TP-03 原始页面图片。

### 3.3 检查原始结果

调用：

```http
GET /api/chapters/{chapter_id}/ocr-runs
```

确认 `normalized_result.artifacts.markdown` 与 `normalized_result.artifacts.json` 仍然存在；`anchored_markdown` 是新增派生内容，不覆盖 MinerU 原始 Markdown。

## 4. 内容质量人工抽查

建议选取至少 3 页、包含正文/页眉/脚注/表格/公式/图片的真实教材样本，检查：

1. 标题和正文映射到正确的原始页。
2. 表格 HTML、公式文本和图片说明仍可在 SourceBlock 中找到。
3. arXiv、DOI、期刊信息只出现在清洗候选中，原文仍保留。
4. 脚注候选独立标记，不会被静默拼入或删除。
5. 跨页重复短文本被标记为重复候选，但正文证据不被删除。
6. 从任意 SourceBlock 的 `page_id` 可以访问对应原图。
7. 对同一 run 重复物化，SourceBlock 数量和 block_key 保持不变。

## 5. 当前限制

- 只有 full.md、没有 content_list.json 时，不生成猜测页码的 SourceBlock；报告会明确提示缺少布局数据。
- bbox 暂按 MinerU 原值保存，不对坐标单位、旋转或归一化做未经验证的转换。
- 清洗仍是候选标注，尚未实现人工审核 UI、可撤销删除视图、跨 OCR 版本锚点迁移。
- 图片文件独立持久化、bbox 原图叠加预览与脚注引用关系将在后续阶段继续完善。
