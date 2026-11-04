# 软考高级教材结构化理解与复习系统

本项目旨在把软考高级教材从“按页阅读的静态文本”转化为“可追溯、可浏览、可复习的结构化知识体系”。

## 当前阶段

TP-01～TP-03 已完成验收。当前在 dev 分支实施 TP-04：OCR Provider 与图像预处理；首版提供 Mock Provider 验证处理链路，尚未接入真实 OCR 引擎。所有正式知识、关系和题目必须能回溯到教材原文来源块。

## 文档

- [产品规格说明书（Spec）](docs/PROJECT_SPEC.md)
- [任务包与实施路线图](docs/TASK_PACKAGES.md)
- [TP-03 图片导入本地验收说明](docs/TP03_ACCEPTANCE.md)
- [TP-04 OCR 本地验收说明](docs/TP04_ACCEPTANCE.md)

## 技术基线

- Python：**3.13.15**
- 后端：FastAPI
- ORM：SQLAlchemy 2.x
- 迁移：Alembic
- 数据库：SQLite 起步，后续可迁移 PostgreSQL
- 测试：pytest；代码检查：Ruff

## Windows 开发环境

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
python -m pip install -U pip
pip install -e ".[dev]"
```

Windows 一键验收（推荐）：

```powershell
.\test.bat
```

也可以直接运行 PowerShell 脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1
```

脚本会使用项目的 `.venv` Python，依次检查 Python 版本、在系统临时目录创建一次性 SQLite 数据库并执行 Alembic 迁移、运行 Ruff 和 pytest。迁移测试库会在结束后清理，不会覆盖正式教材数据库。首次使用前仍需按上方步骤创建虚拟环境并安装 `.[dev]` 依赖。

教材图片导入 API（TP-03）：

- `POST /api/books`、`GET /api/books`：创建和分页查询教材。
- `POST /api/books/{book_id}/chapters`、`GET /api/books/{book_id}/chapters`：创建和查询章节。
- `POST /api/chapters/{chapter_id}/pages`：批量上传 1–30 张 JPEG/PNG/WEBP/TIFF 图片。
- `GET /api/chapters/{chapter_id}/pages`：按页序查询页面。
- `PUT /api/chapters/{chapter_id}/pages/order`：提交完整页面 ID 顺序。
- `PATCH /api/chapters/{chapter_id}/pages/{page_id}/number`：校正教材印刷页码。
- `PATCH /api/chapters/{chapter_id}/pages/{page_id}/rotation`：更新显示旋转角度，不修改原图。
- `PUT /api/chapters/{chapter_id}/pages/{page_id}/replace`：以新页面记录替换，旧原图保留。
- `DELETE /api/chapters/{chapter_id}/pages/{page_id}`：归档页面，不物理删除原图。
- `GET /api/chapters/{chapter_id}/pages/{page_id}/image`：预览原始图片。

默认图片目录为 `./data/uploads`，不进入 Git。可通过 `STORAGE_DIR`、`MAX_IMAGE_BYTES`、`MAX_BATCH_UPLOAD_BYTES`、`MAX_BATCH_UPLOAD_COUNT`、`MAX_IMAGE_PIXELS` 配置上传限制。

OCR 处理 API（TP-04 首版）：

- `POST /api/chapters/{chapter_id}/pages/{page_id}/ocr`：为指定活动页面创建一次 OCR 处理尝试。
- `GET /api/chapters/{chapter_id}/pages/{page_id}/ocr-runs`：查询该页面的 OCR 历史记录。
- 每次 POST 都会新建 ProcessingRun；失败记录不会覆盖，重复 POST 即创建新的重试尝试。
- 默认使用 `mock` Provider，返回明确的模拟标记和空文本块，不会生成虚构 OCR 文本。
- 标准化结果保留文本块类型、顺序、归一化 bbox 和置信度；Provider 原始响应与质量报告分别保存。
- 当前图像预处理为内存派生图，不会改写原始教材图片；透视校正和真实 OCR 引擎留待后续接入。

数据库初始化和检查：

```powershell
alembic upgrade head
alembic current
ruff check .
pytest -v
```

启动服务（默认示例使用 8765 端口；若端口不可用可更换）：

```powershell
uvicorn ruangao_note.main:app --app-dir backend --reload --host 127.0.0.1 --port 8765
```

健康检查与 API 文档：
- http://127.0.0.1:8765/health/live
- http://127.0.0.1:8765/health/ready
- http://127.0.0.1:8765/docs

## 开发约定

- 先保证单章端到端闭环，再扩展到全书架构；目录树与知识点层级分开建模。
- 原始图片、OCR 结果、Markdown、知识结构和学习记录分层保存。
- KnowledgeNode 与 SourceBlock 通过多对多关联；关系边必须有类型、方向、证据和审核状态。
- 大模型只负责候选生成；程序校验和人工审核决定正式内容是否入库。
- 每个任务包独立实现、独立验证、形成可审查的提交。
- 不提交教材原始图片、数据库文件、虚拟环境或 API Key。
