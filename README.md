# 软考高级教材结构化理解与复习系统

本项目旨在把软考高级教材从“按页阅读的静态文本”转化为“可追溯、可浏览、可复习的结构化知识体系”。

## 当前阶段

TP-01～TP-03 已完成验收。TP-04 已提供 Mock OCR 和 MinerU v4 云端章节批量解析入口；TP-05 已建立可追溯的页级原文证据与锚点 Markdown；用户提供的 4 页真实教材报告显示 42/42 布局映射、0 异常空文本，model.json 成功恢复段落。图片资源持久化与现有 MinerU batch 恢复入口已进入实现，待本轮 CI 和 Windows 预览验收。TP-06 已实现基于标题证据的目录识别、人工修正和审计记录，GitHub CI 通过，当前待 Windows 浏览器验收。所有正式知识、关系和题目必须能回溯到教材原文来源块。

## 文档

- [产品规格说明书（Spec）](docs/PROJECT_SPEC.md)
- [任务包与实施路线图](docs/TASK_PACKAGES.md)
- [TP-03 图片导入本地验收说明](docs/TP03_ACCEPTANCE.md)
- [TP-04 OCR 本地验收说明](docs/TP04_ACCEPTANCE.md)
- [TP-05 原文证据块与 Markdown 验收说明](docs/TP05_ACCEPTANCE.md)
- [TP-06 目录结构识别与人工修正验收说明](docs/TP06_ACCEPTANCE.md)
- 原文证据与 OCR 清洗工作台：`http://127.0.0.1:8765/source-review`（启动服务后访问）
- 目录结构识别与修正工作台：`http://127.0.0.1:8765/outline-review`（启动服务后访问）

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

MinerU 网络诊断（Windows 一键运行）：

- 双击项目根目录的 `diagnose_mineru_network.bat` 即可运行，无需激活 Python 虚拟环境。
- 也可执行：`powershell -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\diagnose_mineru_network.ps1`。
- 自动检查 `mineru.net` 和 `cdn-mineru.openxlab.org.cn` 的 DNS、TCP 443、TLS 1.2，并分别通过 curl 与 Python httpx 测试直连和显式使用当前用户代理；输出 HTTP 状态码、远端 IP、Python/httpx 版本及异常信息。
- 诊断日志自动保存在项目根目录，文件名为 `mineru_network_diagnostic_时间戳.txt`。把日志发给开发者即可分析。
- 脚本只做网络诊断，不读取 `.env`、不读取/打印 MinerU Token、不提交 OCR、不修改系统代理或防火墙。CDN 根路径返回 403/404/405 也可能代表网络链路已成功到达服务器；不能据此保证签名 ZIP 下载一定成功。应用内 MinerU 结果 ZIP 下载默认明确使用直连（不继承环境变量或系统代理），并记录下载主机、HTTP 状态、重试次数、接收字节数和代理模式。若部署环境确实要求代理，可在本地 `.env` 显式设置 `MINERU_DOWNLOAD_PROXY=http://127.0.0.1:7890`；该设置只作用于结果 ZIP 下载，不影响 MinerU API 请求。不要把代理账号密码提交到 Git。

OCR 处理 API（TP-04）：

- `POST /api/chapters/{chapter_id}/ocr`：把该章节全部活动页面按 `sort_order` 合成为一个多页 PDF，提交一个 MinerU v4 云端 batch 任务。
- `GET /api/chapters/{chapter_id}/ocr-runs`：查询该章节的 MinerU 处理历史。
- `POST /api/chapters/{chapter_id}/pages/{page_id}/ocr`：为指定活动页面创建一次 Mock OCR 处理尝试。
- 每次 POST 都会新建 ProcessingRun；失败记录不会覆盖，重复 POST 即创建新的处理尝试。
- 单页 Mock Provider 明确返回模拟标记和空文本块，不会生成虚构 OCR 文本。
- 章节 MinerU 接口使用 v4 流程：申请批量上传地址 → 预签名 PUT → 轮询 batch → 下载 ZIP。
- Token 只从项目根目录本地 `.env` 的 `MINERU_TOKEN` 读取。运行 `.\scripts\configure_mineru.ps1` 可隐藏输入并保存，不需要把 Token 发到聊天或提交 Git。
- `.env` 已在 `.gitignore` 中排除；`.env.example` 只包含空变量。
- 章节 PDF 是临时内存产物，按页面顺序构建；原始图片不会被修改。
- MinerU 的原始 Markdown/JSON 解析产物保存在章节级 ProcessingRun；TP-05 从 `content_list_v2.json` 优先生成按页关联的 SourceBlock 和带锚点 Markdown，并标记疑似水印、脚注及跨页重复短文本。清洗仅生成审核候选，不会静默删除原文。
- MinerU ZIP 内 JPG/JPEG/PNG/WEBP/TIFF 图片资源会在格式与像素校验后按 SHA-256 独立保存到 `STORAGE_DIR/books/{book}/{chapter}/ocr/{run}/assets`；二进制不写入数据库 JSON。
- 对此前已成功的 MinerU run，可在 `/source-review` 点击“从已有 MinerU 任务恢复图片资源（不重跑 OCR）”；通过原 batch_id 重新下载 ZIP，不重新上传章节 PDF。

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
- http://127.0.0.1:8765/source-review（TP-05 原文证据与 OCR 清洗工作台）
- http://127.0.0.1:8765/outline-review（TP-06 目录结构识别与修正工作台）

## 开发约定

- 先保证单章端到端闭环，再扩展到全书架构；目录树与知识点层级分开建模。
- 原始图片、OCR 结果、Markdown、知识结构和学习记录分层保存。
- KnowledgeNode 与 SourceBlock 通过多对多关联；关系边必须有类型、方向、证据和审核状态。
- 大模型只负责候选生成；程序校验和人工审核决定正式内容是否入库。
- 每个任务包独立实现、独立验证、形成可审查的提交。
- 不提交教材原始图片、数据库文件、虚拟环境或 API Key。
