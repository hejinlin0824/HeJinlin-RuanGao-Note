# 软考高级教材结构化理解与复习系统

本项目旨在把软考高级教材从“按页阅读的静态文本”转化为“可追溯、可浏览、可复习的结构化知识体系”。

## 当前阶段

产品规格与任务包已落盘。当前在 dev 分支推进 TP-01：Python 环境与项目骨架。所有正式知识、关系和题目必须能回溯到教材原文来源块。

## 文档

- [产品规格说明书（Spec）](docs/PROJECT_SPEC.md)
- [任务包与实施路线图](docs/TASK_PACKAGES.md)

## 技术基线

- Python：**3.13.15**
- 后端：FastAPI
- 数据访问：SQLAlchemy 2.x（TP-02 开始接入实际模型）
- 数据库：SQLite 起步，后续可迁移 PostgreSQL
- 测试：pytest；代码检查：Ruff

## Windows 开发环境

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
python -m pip install -U pip
pip install -e ".[dev]"
uvicorn ruangao_note.main:app --app-dir backend --reload
```

健康检查：
- http://127.0.0.1:8000/health/live
- http://127.0.0.1:8000/health/ready
- http://127.0.0.1:8000/docs

运行检查：
```powershell
ruff check .
pytest
```

## 开发约定

- 先保证单章端到端闭环，再扩展到全书架构；数据模型从第一天支持 Book / Chapter / Section / KnowledgeNode。
- 原始图片、OCR 结果、Markdown、知识结构和学习记录分层保存。
- 大模型只负责候选生成；程序校验和人工审核决定正式内容是否入库。
- 每个任务包独立实现、独立验证、形成可审查的提交。
- 不提交教材原始图片、数据库文件、虚拟环境或 API Key。
