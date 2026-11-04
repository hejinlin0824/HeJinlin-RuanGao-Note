# 软考高级教材结构化理解与复习系统

本项目旨在把软考高级教材从“按页阅读的静态文本”转化为“可追溯、可浏览、可复习的结构化知识体系”。

## 当前阶段

TP-01 项目骨架已在 Python 3.13.15 环境完成本地验收。当前在 dev 分支推进 TP-02：领域模型与数据库；数据库迁移和模型测试仍需在开发机执行确认。所有正式知识、关系和题目必须能回溯到教材原文来源块。

## 文档

- [产品规格说明书（Spec）](docs/PROJECT_SPEC.md)
- [任务包与实施路线图](docs/TASK_PACKAGES.md)

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
