# TP-04 OCR Provider 与图像预处理验收

## 1. 环境准备

在 Windows 项目根目录、Python 3.13.15 虚拟环境中执行：

```powershell
git pull origin dev
python -m pip install -e ".[dev]"
.\test.bat
```

预期：Python 版本检查、Alembic 迁移、Ruff、pytest 全部通过。

## 2. 数据库迁移

```powershell
alembic upgrade head
alembic current
```

预期版本为 `0003_ocr_results`。既有 `processing_runs` 记录的新增 JSON 字段允许为空，不应丢失历史运行记录。

## 3. 启动服务

```powershell
uvicorn ruangao_note.main:app --app-dir backend --reload --host 127.0.0.1 --port 8765
```

打开 http://127.0.0.1:8765/docs。

## 4. OCR API 验收

1. 先按 TP-03 流程创建教材、章节并上传一张有效页面图片。
2. 调用 `POST /api/chapters/{chapter_id}/pages/{page_id}/ocr`。
3. 预期返回 `status=succeeded`、`provider=mock`、`raw_result.simulated=true`。
4. `normalized_result.schema_version` 为 `1.0`，`blocks` 是空数组。Mock 不会虚构教材文字。
5. `quality_report` 应包含图像宽高、灰度标准差、边缘标准差、空白/模糊提示和 warnings。
6. 调用 `GET /api/chapters/{chapter_id}/pages/{page_id}/ocr-runs`，应看到刚刚生成的处理记录。
7. 再次调用 POST，应生成新的 run ID；不得覆盖上一次记录。
8. 归档该页面后再次调用 POST，应返回 404；历史 OCR 记录仍可查询。

## 5. 原图完整性检查

调用 OCR 前后，通过 TP-03 图片预览接口获取原图，确认原图仍可读取。数据库 `chapter_pages.sha256` 不变；OCR 预处理只生成内存派生数据，不修改原图文件。

## 6. 当前明确不在验收范围内

- 真实 OCR 文字识别准确率；
- 云端 API Key、计费、限流与异步任务队列；
- 自动倾斜角估计、透视矫正和智能裁边；
- 自动创建 SourceBlock 或 Markdown（属于 TP-05）。
