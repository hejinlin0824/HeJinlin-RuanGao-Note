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

## 3. 前端工作台验收

启动服务后打开：

`http://127.0.0.1:8765/source-review`

在页面选择教材、章节和成功的 OCR 处理记录，点击“生成 / 补全原文块”。页面会显示布局文件选择、块数量、空文本块数量、页码映射数量和清洗候选，并可查看原始教材页及导出锚点 Markdown。若报告提示图片资源尚未持久化，点击“从已有 MinerU 任务恢复图片资源（不重跑 OCR）”；系统使用已保存的 batch_id 下载原结果 ZIP，不会重新提交章节 PDF。普通使用无需操作 Swagger 或手工输入 API。

若此前已经生成过空文本 SourceBlock，再次点击“生成 / 补全原文块”会按原布局顺序修复现有记录，尽量保留 SourceBlock ID 和已有证据关系；不需要重新上传图片或运行 MinerU。

## 4. API 验收

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

## 5. 内容质量人工抽查

建议选取至少 3 页、包含正文/页眉/脚注/表格/公式/图片的真实教材样本，检查：

1. 标题和正文映射到正确的原始页。
2. 表格 HTML、公式文本和图片说明仍可在 SourceBlock 中找到。
3. arXiv、DOI、期刊信息只出现在清洗候选中，原文仍保留。
4. 脚注候选独立标记，不会被静默拼入或删除。
5. 跨页重复短文本被标记为重复候选，但正文证据不被删除。
6. 从任意 SourceBlock 的 `page_id` 可以访问对应原图。
7. 对同一 run 重复物化，SourceBlock 数量和 block_key 保持不变。

## 6. MinerU 图片资源持久化

- ZIP 解压除 Markdown/JSON 外，也会提取 JPG/JPEG/PNG/WEBP/TIFF 图片；单文件上限 20 MiB、累计提取上限 200 MiB，整个 ZIP 解压总量仍受 1 GiB 限制。
- 图片字节先经 Pillow 格式/像素校验，再写入 `STORAGE_DIR/books/{book}/{chapter}/ocr/{run}/assets/`；磁盘文件名由 SHA-256 生成，不直接使用 ZIP 内路径。
- `SourceBlock.media_path` 保存 content_list 中的原始资源路径；ProcessingRun artifact 元数据记录存储路径、SHA-256、MIME、大小和图片尺寸。二进制不写入 SQLite JSON。
- 已有成功 OCR run 可使用工作台恢复按钮，从原 MinerU batch 再下载 ZIP；不重跑 OCR、不重新上传 PDF。若 MinerU 已过期或不再提供 ZIP，则恢复会返回明确错误，届时只能创建新的 OCR run。
- 工作台会并列显示教材原始整页和 MinerU 提取的图片资源。bbox 精确叠加、旋转坐标转换、SVG 等矢量资源仍不在本阶段范围内。

## 7. 当前限制

- 优先解析 `content_list_v2.json`：识别按页分组结构及 `title_content`、`paragraph_content`、`math_content`、脚注等 span 字段；缺少 V2 时回退至 `content_list.json`。
- 只有 full.md、没有可用 content_list 时，不生成猜测页码的 SourceBlock；报告会明确提示缺少布局数据。
- bbox 暂按 MinerU 原值保存，不对坐标单位、旋转或归一化做未经验证的转换。
- 清洗仍是候选标注，尚未实现人工审核 UI、可撤销删除视图、跨 OCR 版本锚点迁移。
- bbox 到教材整页的精确叠加、旋转坐标转换和脚注引用关系将在后续阶段继续完善。
