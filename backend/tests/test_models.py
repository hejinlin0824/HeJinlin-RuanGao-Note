"""Database and domain-model integration tests."""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ruangao_note.db.base import Base
from ruangao_note.db.session import create_database_engine
from ruangao_note.domain.models import (
    Book,
    Chapter,
    ChapterPage,
    KnowledgeNode,
    KnowledgeSource,
    ProcessingRun,
    Relation,
    RelationEvidence,
    Section,
    SourceBlock,
)


def make_session() -> tuple[Session, Engine]:
    """Create an isolated in-memory SQLite database for one test."""
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine), engine


def test_initial_schema_contains_all_domain_tables() -> None:
    session, engine = make_session()
    try:
        tables = set(inspect(engine).get_table_names())
        assert {
            "books",
            "chapters",
            "sections",
            "chapter_pages",
            "processing_runs",
            "source_blocks",
            "knowledge_nodes",
            "knowledge_sources",
            "relations",
            "relation_evidence",
            "figures",
            "audit_issues",
            "audit_events",
            "questions",
            "question_sources",
            "review_states",
            "answer_logs",
        } <= tables
    finally:
        session.close()
        engine.dispose()


def test_knowledge_nodes_and_source_blocks_are_many_to_many() -> None:
    session, engine = make_session()
    try:
        book = Book(title="软件设计师教程")
        chapter = Chapter(book=book, chapter_number=1, title="计算机系统基础")
        page = ChapterPage(
            chapter=chapter,
            sort_order=0,
            textbook_page_number=1,
            original_filename="page-001.png",
            storage_path="books/demo/page-001.png",
            sha256="a" * 64,
            mime_type="image/png",
            byte_size=1024,
        )
        run = ProcessingRun(
            chapter=chapter,
            page=page,
            task_type="ocr",
            provider="mock",
            status="succeeded",
        )
        source = SourceBlock(
            chapter=chapter,
            page=page,
            processing_run=run,
            block_key="p1_b1",
            block_type="paragraph",
            text="计算机系统由硬件和软件组成。",
            confidence=0.98,
        )
        node_a = KnowledgeNode(chapter=chapter, name="计算机硬件")
        node_b = KnowledgeNode(chapter=chapter, name="计算机软件")
        node_a.sources.append(KnowledgeSource(source_block=source, role="definition"))
        node_b.sources.append(KnowledgeSource(source_block=source, role="evidence"))
        relation = Relation(
            source_node=node_a,
            target_node=node_b,
            relation_type="contrast",
            origin="text_explicit",
            status="needs_review",
        )
        relation.evidence.append(RelationEvidence(source_block=source, role="support"))

        session.add_all([node_a, node_b, relation])
        session.commit()

        assert len(node_a.sources) == 1
        assert len(node_b.sources) == 1
        assert node_a.sources[0].source_block_id == source.id
        assert node_b.sources[0].source_block_id == source.id
        assert relation.evidence[0].source_block_id == source.id
    finally:
        session.close()
        engine.dispose()


def test_toc_tree_is_separate_from_knowledge_tree() -> None:
    session, engine = make_session()
    try:
        book = Book(title="软件设计师教程")
        chapter = Chapter(book=book, chapter_number=1, title="基础知识")
        section = Section(chapter=chapter, title="计算机系统", level=1, sort_order=0)
        subsection = Section(
            chapter=chapter, parent=section, title="计算机组成", level=2, sort_order=0
        )
        knowledge_parent = KnowledgeNode(chapter=chapter, name="计算机系统")
        knowledge_child = KnowledgeNode(
            chapter=chapter, parent=knowledge_parent, name="存储系统"
        )
        session.add_all([subsection, knowledge_child])
        session.commit()

        assert subsection.parent_id == section.id
        assert knowledge_child.parent_id == knowledge_parent.id
        assert subsection.id != knowledge_child.id
    finally:
        session.close()
        engine.dispose()


def test_relation_requires_a_complete_endpoint_pair() -> None:
    session, engine = make_session()
    try:
        node = KnowledgeNode(name="孤立知识点")
        session.add(node)
        session.flush()
        invalid_relation = Relation(
            source_node=node,
            relation_type="prerequisite",
            status="needs_review",
        )
        session.add(invalid_relation)

        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("A relation without a target must violate its check constraint.")
    finally:
        session.close()
        engine.dispose()


def test_sqlite_foreign_keys_are_enabled() -> None:
    session, engine = make_session()
    try:
        assert session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    finally:
        session.close()
        engine.dispose()
