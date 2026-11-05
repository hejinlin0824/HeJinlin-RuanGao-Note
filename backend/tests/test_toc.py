"""TP-06 regression tests for rule-based outline extraction and manual correction."""

from pathlib import Path

from fastapi.testclient import TestClient
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from ruangao_note.core.config import get_settings

from ruangao_note.db.base import Base
from ruangao_note.db.session import create_database_engine, get_db
from ruangao_note.domain.models import (
    AuditEvent,
    AuditIssue,
    Book,
    Chapter,
    ChapterPage,
    ProcessingRun,
    Section,
    SourceBlock,
)
from ruangao_note.main import app
from ruangao_note.services.toc import (
    TOCNotFoundError,
    TOCService,
    TOCValidationError,
)


def _context():
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    book = Book(title="信息系统项目管理师教程")
    chapter = Chapter(book=book, chapter_number=1, title="第1章 信息化发展")
    page = ChapterPage(
        chapter=chapter,
        sort_order=0,
        textbook_page_number=2,
        original_filename="page-002.png",
        storage_path="books/demo/page-002.png",
        sha256="a" * 64,
        mime_type="image/png",
        byte_size=100,
        width=1000,
        height=1400,
    )
    run = ProcessingRun(
        chapter=chapter,
        page=None,
        task_type="chapter_ocr",
        provider="mineru_cloud",
        provider_version="vlm",
        status="succeeded",
    )
    session.add_all([book, chapter, page, run])
    session.flush()
    return engine, session, chapter, page, run


def _add_headings(session, chapter, page, run, texts):
    blocks = []
    for index, text in enumerate(texts):
        block = SourceBlock(
            chapter_id=chapter.id,
            page_id=page.id,
            processing_run_id=run.id,
            block_key=f"heading-{index}",
            block_type="heading",
            text=text,
            bbox=[20, index * 30, 900, index * 30 + 24],
            content_hash=f"{index + 1:064x}",
            sort_order=index,
            is_active=True,
        )
        blocks.append(block)
    session.add_all(blocks)
    session.flush()
    return blocks


def test_toc_generation_builds_hierarchy_and_is_idempotent():
    engine, session, chapter, page, run = _context()
    try:
        blocks = _add_headings(
            session,
            chapter,
            page,
            run,
            [
                "第1章 信息化发展",
                "1.1 信息与信息化",
                "1.1.1 信息",
                "1. 信息的定义",
                "2. 信息的特征与质量",
                "1.1.2 信息系统",
                "1. 信息系统及其特性",
                "1.1.3 信息化",
                "1. 信息化内涵",
            ],
        )
        session.commit()

        service = TOCService(session)
        first_report = service.generate(chapter.id)
        session.commit()
        sections = session.scalars(
            select(Section)
            .where(Section.chapter_id == chapter.id)
            .order_by(Section.sort_order, Section.id)
        ).all()
        by_source = {section.source_block_id: section for section in sections}

        assert first_report["source_heading_count"] == 9
        assert first_report["created_count"] == 8
        assert first_report["skipped_chapter_heading_count"] == 1
        assert len(sections) == 8

        section_11 = by_source[blocks[1].id]
        section_111 = by_source[blocks[2].id]
        definition = by_source[blocks[3].id]
        characteristics = by_source[blocks[4].id]
        section_112 = by_source[blocks[5].id]
        assert section_11.level == 1
        assert section_111.level == 2
        assert section_111.parent_id == section_11.id
        assert definition.level == 3
        assert definition.parent_id == section_111.id
        assert characteristics.parent_id == section_111.id
        assert section_112.level == 2
        assert section_112.parent_id == section_11.id

        second_report = service.generate(chapter.id)
        session.commit()
        assert second_report["created_count"] == 0
        assert second_report["already_linked_count"] == 8
        assert session.scalars(
            select(Section).where(Section.chapter_id == chapter.id)
        ).all().__len__() == 8
    finally:
        session.close()
        engine.dispose()


def test_toc_keeps_missing_parent_heading_and_creates_audit_issue():
    engine, session, chapter, page, run = _context()
    try:
        blocks = _add_headings(session, chapter, page, run, ["2.3.1 缺失父级的标题"])
        session.commit()

        report = TOCService(session).generate(chapter.id)
        session.commit()
        section = session.scalar(
            select(Section).where(Section.source_block_id == blocks[0].id)
        )
        issue = session.scalar(
            select(AuditIssue).where(
                AuditIssue.entity_type == "section",
                AuditIssue.entity_id == section.id,
                AuditIssue.issue_type == "missing_parent_section",
            )
        )

        assert report["created_count"] == 1
        assert section is not None
        assert section.parent_id is None
        assert section.level == 2
        assert issue is not None
        assert issue.status == "open"
        assert issue.evidence_source_block_id == blocks[0].id
    finally:
        session.close()
        engine.dispose()


def test_manual_outline_edit_is_audited_and_rejects_cycles():
    engine, session, chapter, page, run = _context()
    try:
        blocks = _add_headings(
            session, chapter, page, run, ["1.1 基础", "1.1.1 子目录"]
        )
        session.commit()
        TOCService(session).generate(chapter.id)
        session.commit()
        root = session.scalar(
            select(Section).where(Section.source_block_id == blocks[0].id)
        )
        child = session.scalar(
            select(Section).where(Section.source_block_id == blocks[1].id)
        )

        updated = TOCService(session).update_section(
            chapter.id,
            child.id,
            {"title": "人工修正后的子目录", "section_number": "1.1.1", "level": 2},
            actor="reviewer",
            reason="核对教材原页后修正标题",
        )
        session.commit()
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.entity_type == "section",
                AuditEvent.entity_id == child.id,
                AuditEvent.action == "toc_manual_updated",
            )
        )
        assert updated.title == "人工修正后的子目录"
        assert event is not None
        assert event.actor == "reviewer"
        assert event.before_data["title"] == "子目录"
        assert event.after_data["title"] == "人工修正后的子目录"

        try:
            TOCService(session).update_section(
                chapter.id, root.id, {"parent_id": child.id, "level": 3}
            )
        except TOCValidationError as exc:
            assert "ancestor" in str(exc)
        else:
            raise AssertionError("A parent/child cycle must be rejected.")
    finally:
        session.close()
        engine.dispose()


def test_toc_service_rejects_unknown_chapter():
    engine, session, _chapter, _page, _run = _context()
    try:
        try:
            TOCService(session).generate("missing-chapter")
        except TOCNotFoundError:
            pass
        else:
            raise AssertionError("Unknown chapters must be rejected.")
    finally:
        session.close()
        engine.dispose()


def test_outline_api_generates_lists_and_manually_updates_sections(tmp_path):
    database_path = (tmp_path / "outline-api.db").as_posix()
    engine = create_database_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    with factory() as session:
        book = Book(title="API 教材")
        chapter = Chapter(book=book, chapter_number=1, title="第1章 基础")
        page = ChapterPage(
            chapter=chapter,
            sort_order=0,
            original_filename="page.png",
            storage_path="api/page.png",
            sha256="b" * 64,
            mime_type="image/png",
            byte_size=20,
            width=100,
            height=100,
        )
        run = ProcessingRun(
            chapter=chapter,
            task_type="chapter_ocr",
            provider="mineru_cloud",
            status="succeeded",
        )
        session.add_all([book, chapter, page, run])
        session.flush()
        block = SourceBlock(
            chapter_id=chapter.id,
            page_id=page.id,
            processing_run_id=run.id,
            block_key="api-heading-1",
            block_type="heading",
            text="1.1 API 目录",
            content_hash="c" * 64,
            sort_order=0,
        )
        session.add(block)
        session.commit()
        chapter_id = chapter.id

    def override_get_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            generated = client.post(
                f"/api/chapters/{chapter_id}/sections/generate"
            )
            assert generated.status_code == 200
            body = generated.json()
            assert body["report"]["created_count"] == 1
            assert body["count"] == 1
            section = body["items"][0]
            assert section["source_block_id"]
            assert section["source_text"] == "1.1 API 目录"
            assert section["image_url"].endswith("/image")

            updated = client.patch(
                f"/api/chapters/{chapter_id}/sections/{section['id']}",
                json={
                    "title": "人工确认的 API 目录",
                    "section_number": "1.1",
                    "level": 1,
                    "parent_id": None,
                    "sort_order": 2,
                    "actor": "tester",
                    "reason": "API regression test",
                },
            )
            assert updated.status_code == 200
            assert updated.json()["title"] == "人工确认的 API 目录"
            assert updated.json()["sort_order"] == 2

            listed = client.get(f"/api/chapters/{chapter_id}/sections")
            assert listed.status_code == 200
            assert listed.json()["items"][0]["title"] == "人工确认的 API 目录"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()



def test_0004_migration_adds_source_link_to_legacy_sections_table(
    tmp_path, monkeypatch
):
    """An older database without source_block_id must upgrade without table recreation."""
    database_path = tmp_path / "legacy-outline.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    get_settings.cache_clear()
    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "alembic.ini"))

    try:
        # The historical 0001 migration uses current metadata; emulate a database
        # created before TP-06 by removing the new nullable column and its index.
        command.upgrade(config, "0003_ocr_results")
        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "DROP INDEX IF EXISTS ix_sections_source_block_id"
            )
            connection.exec_driver_sql(
                "ALTER TABLE sections DROP COLUMN source_block_id"
            )
        engine.dispose()

        command.upgrade(config, "head")

        migrated_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        try:
            inspector = inspect(migrated_engine)
            columns = {column["name"] for column in inspector.get_columns("sections")}
            foreign_keys = inspector.get_foreign_keys("sections")
            indexes = {index["name"] for index in inspector.get_indexes("sections")}
            assert "source_block_id" in columns
            assert any(
                foreign_key["constrained_columns"] == ["source_block_id"]
                and foreign_key["referred_table"] == "source_blocks"
                for foreign_key in foreign_keys
            )
            assert "ix_sections_source_block_id" in indexes
        finally:
            migrated_engine.dispose()
    finally:
        get_settings.cache_clear()
