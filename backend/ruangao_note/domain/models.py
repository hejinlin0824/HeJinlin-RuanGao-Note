"""SQLAlchemy models for the textbook, evidence, knowledge, and review domains."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ruangao_note.db.base import Base, TimestampMixin, utc_now


def new_id() -> str:
    """Generate a portable UUID string primary key."""
    return str(uuid4())


class Book(TimestampMixin, Base):
    """A textbook or study source."""

    __tablename__ = "books"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    edition: Mapped[str | None] = mapped_column(String(120))
    exam_track: Mapped[str | None] = mapped_column(String(160))
    publisher: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)

    chapters: Mapped[list[Chapter]] = relationship(back_populates="book")


class Chapter(TimestampMixin, Base):
    """A numbered chapter belonging to a book."""

    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint("book_id", "chapter_number", name="uq_chapter_book_number"),
        UniqueConstraint("book_id", "sort_order", name="uq_chapter_book_sort"),
        CheckConstraint("chapter_number > 0", name="ck_chapter_number_positive"),
        CheckConstraint("sort_order >= 0", name="ck_chapter_sort_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    book_id: Mapped[str] = mapped_column(
        ForeignKey("books.id", ondelete="RESTRICT"), nullable=False
    )
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)

    book: Mapped[Book] = relationship(back_populates="chapters")
    sections: Mapped[list[Section]] = relationship(back_populates="chapter")
    pages: Mapped[list[ChapterPage]] = relationship(back_populates="chapter")
    processing_runs: Mapped[list[ProcessingRun]] = relationship(back_populates="chapter")
    source_blocks: Mapped[list[SourceBlock]] = relationship(back_populates="chapter")
    knowledge_nodes: Mapped[list[KnowledgeNode]] = relationship(back_populates="chapter")


class Section(TimestampMixin, Base):
    """A node in the textbook's table-of-contents tree."""

    __tablename__ = "sections"
    __table_args__ = (
        CheckConstraint("level > 0", name="ck_section_level_positive"),
        CheckConstraint("sort_order >= 0", name="ck_section_sort_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("chapters.id", ondelete="RESTRICT"), nullable=False
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("sections.id", ondelete="RESTRICT")
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    section_number: Mapped[str | None] = mapped_column(String(80))
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    chapter: Mapped[Chapter] = relationship(back_populates="sections")
    parent: Mapped[Section | None] = relationship(
        remote_side="Section.id", back_populates="children"
    )
    children: Mapped[list[Section]] = relationship(back_populates="parent")
    knowledge_nodes: Mapped[list[KnowledgeNode]] = relationship(back_populates="section")


class ChapterPage(TimestampMixin, Base):
    """An immutable original textbook page image and its ordering metadata."""

    __tablename__ = "chapter_pages"
    __table_args__ = (
        UniqueConstraint("chapter_id", "sort_order", name="uq_page_chapter_sort"),
        CheckConstraint("sort_order >= 0", name="ck_page_sort_nonnegative"),
        CheckConstraint("byte_size >= 0", name="ck_page_size_nonnegative"),
        CheckConstraint("rotation IN (0, 90, 180, 270)", name="ck_page_rotation"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("chapters.id", ondelete="RESTRICT"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    textbook_page_number: Mapped[int | None] = mapped_column(Integer)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    rotation: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="stored", nullable=False)

    chapter: Mapped[Chapter] = relationship(back_populates="pages")
    processing_runs: Mapped[list[ProcessingRun]] = relationship(back_populates="page")
    source_blocks: Mapped[list[SourceBlock]] = relationship(back_populates="page")
    figures: Mapped[list[Figure]] = relationship(back_populates="page")


class ProcessingRun(TimestampMixin, Base):
    """A versioned OCR, layout, or model-processing attempt."""

    __tablename__ = "processing_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_processing_run_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("chapters.id", ondelete="RESTRICT"), nullable=False
    )
    page_id: Mapped[str | None] = mapped_column(
        ForeignKey("chapter_pages.id", ondelete="RESTRICT")
    )
    task_type: Mapped[str] = mapped_column(String(60), nullable=False)
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_version: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(24), default="queued", nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    raw_result: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    chapter: Mapped[Chapter] = relationship(back_populates="processing_runs")
    page: Mapped[ChapterPage | None] = relationship(back_populates="processing_runs")
    source_blocks: Mapped[list[SourceBlock]] = relationship(back_populates="processing_run")


class SourceBlock(TimestampMixin, Base):
    """A versioned, page-locatable evidence block extracted from source material."""

    __tablename__ = "source_blocks"
    __table_args__ = (
        UniqueConstraint("processing_run_id", "block_key", name="uq_source_run_block_key"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
                        name="ck_source_confidence_range"),
        CheckConstraint("version > 0", name="ck_source_version_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("chapters.id", ondelete="RESTRICT"), nullable=False
    )
    page_id: Mapped[str] = mapped_column(
        ForeignKey("chapter_pages.id", ondelete="RESTRICT"), nullable=False
    )
    processing_run_id: Mapped[str] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="RESTRICT"), nullable=False
    )
    block_key: Mapped[str] = mapped_column(String(120), nullable=False)
    block_type: Mapped[str] = mapped_column(String(40), nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    bbox: Mapped[dict[str, float] | list[float] | None] = mapped_column(JSON)
    confidence: Mapped[float | None] = mapped_column(Float)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    chapter: Mapped[Chapter] = relationship(back_populates="source_blocks")
    page: Mapped[ChapterPage] = relationship(back_populates="source_blocks")
    processing_run: Mapped[ProcessingRun] = relationship(back_populates="source_blocks")
    knowledge_sources: Mapped[list[KnowledgeSource]] = relationship(back_populates="source_block")
    relation_evidence: Mapped[list[RelationEvidence]] = relationship(back_populates="source_block")


class KnowledgeNode(TimestampMixin, Base):
    """A learning-oriented knowledge node, separate from the TOC tree."""

    __tablename__ = "knowledge_nodes"
    __table_args__ = (
        CheckConstraint("sort_order >= 0", name="ck_knowledge_sort_nonnegative"),
        CheckConstraint(
            "status IN ('draft', 'needs_review', 'approved', 'rejected')",
            name="ck_knowledge_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chapter_id: Mapped[str | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="RESTRICT")
    )
    section_id: Mapped[str | None] = mapped_column(
        ForeignKey("sections.id", ondelete="RESTRICT")
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_nodes.id", ondelete="RESTRICT")
    )
    node_type: Mapped[str] = mapped_column(String(40), default="concept", nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    definition: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)
    key_points: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    chapter: Mapped[Chapter | None] = relationship(back_populates="knowledge_nodes")
    section: Mapped[Section | None] = relationship(back_populates="knowledge_nodes")
    parent: Mapped[KnowledgeNode | None] = relationship(
        remote_side="KnowledgeNode.id", back_populates="children"
    )
    children: Mapped[list[KnowledgeNode]] = relationship(back_populates="parent")
    sources: Mapped[list[KnowledgeSource]] = relationship(back_populates="knowledge_node")
    outgoing_relations: Mapped[list[Relation]] = relationship(
        foreign_keys="Relation.source_node_id", back_populates="source_node"
    )
    incoming_relations: Mapped[list[Relation]] = relationship(
        foreign_keys="Relation.target_node_id", back_populates="target_node"
    )
    questions: Mapped[list[Question]] = relationship(back_populates="knowledge_node")


class KnowledgeSource(Base):
    """Many-to-many evidence link between a knowledge node and source block."""

    __tablename__ = "knowledge_sources"

    knowledge_node_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id", ondelete="RESTRICT"), primary_key=True
    )
    source_block_id: Mapped[str] = mapped_column(
        ForeignKey("source_blocks.id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(40), default="evidence", nullable=False)
    quote_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    knowledge_node: Mapped[KnowledgeNode] = relationship(back_populates="sources")
    source_block: Mapped[SourceBlock] = relationship(back_populates="knowledge_sources")


class Relation(TimestampMixin, Base):
    """An evidence-backed directed edge between two chapters or two knowledge nodes."""

    __tablename__ = "relations"
    __table_args__ = (
        CheckConstraint(
            "(source_node_id IS NOT NULL AND target_node_id IS NOT NULL "
            "AND source_chapter_id IS NULL AND target_chapter_id IS NULL) OR "
            "(source_node_id IS NULL AND target_node_id IS NULL "
            "AND source_chapter_id IS NOT NULL AND target_chapter_id IS NOT NULL)",
            name="ck_relation_endpoint_pair",
        ),
        CheckConstraint("source_node_id IS NULL OR source_node_id != target_node_id",
                        name="ck_relation_node_not_self"),
        CheckConstraint("source_chapter_id IS NULL OR source_chapter_id != target_chapter_id",
                        name="ck_relation_chapter_not_self"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
                        name="ck_relation_confidence_range"),
        CheckConstraint(
            "relation_type IN ('contains', 'prerequisite', 'sequence', 'causes', "
            "'contrast', 'association', 'application', 'implements', 'example_of', 'same_as')",
            name="ck_relation_type",
        ),
        CheckConstraint("direction IN ('directed', 'undirected')", name="ck_relation_direction"),
        CheckConstraint(
            "origin IN ('text_explicit', 'human_inferred', 'model_candidate', 'system_derived')",
            name="ck_relation_origin",
        ),
        CheckConstraint(
            "status IN ('draft', 'needs_review', 'approved', 'rejected')",
            name="ck_relation_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_node_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_nodes.id", ondelete="RESTRICT")
    )
    target_node_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_nodes.id", ondelete="RESTRICT")
    )
    source_chapter_id: Mapped[str | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="RESTRICT")
    )
    target_chapter_id: Mapped[str | None] = mapped_column(
        ForeignKey("chapters.id", ondelete="RESTRICT")
    )
    relation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), default="directed", nullable=False)
    origin: Mapped[str] = mapped_column(String(24), default="model_candidate", nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="needs_review", nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    source_node: Mapped[KnowledgeNode | None] = relationship(
        foreign_keys=[source_node_id], back_populates="outgoing_relations"
    )
    target_node: Mapped[KnowledgeNode | None] = relationship(
        foreign_keys=[target_node_id], back_populates="incoming_relations"
    )
    evidence: Mapped[list[RelationEvidence]] = relationship(back_populates="relation")


class RelationEvidence(Base):
    """Evidence blocks supporting a proposed or approved relation edge."""

    __tablename__ = "relation_evidence"

    relation_id: Mapped[str] = mapped_column(
        ForeignKey("relations.id", ondelete="RESTRICT"), primary_key=True
    )
    source_block_id: Mapped[str] = mapped_column(
        ForeignKey("source_blocks.id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(40), default="support", nullable=False)
    quote_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    relation: Mapped[Relation] = relationship(back_populates="evidence")
    source_block: Mapped[SourceBlock] = relationship(back_populates="relation_evidence")


class Figure(TimestampMixin, Base):
    """A figure or diagram extracted from a textbook page."""

    __tablename__ = "figures"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("chapters.id", ondelete="RESTRICT"), nullable=False
    )
    page_id: Mapped[str] = mapped_column(
        ForeignKey("chapter_pages.id", ondelete="RESTRICT"), nullable=False
    )
    source_block_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_blocks.id", ondelete="RESTRICT")
    )
    figure_type: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    caption: Mapped[str | None] = mapped_column(Text)
    bbox: Mapped[dict[str, float] | list[float] | None] = mapped_column(JSON)
    mermaid_source: Mapped[str | None] = mapped_column(Text)
    render_status: Mapped[str] = mapped_column(String(32), default="not_attempted", nullable=False)
    fallback_reason: Mapped[str | None] = mapped_column(Text)

    page: Mapped[ChapterPage] = relationship(back_populates="figures")


class AuditIssue(TimestampMixin, Base):
    """A machine- or human-detected issue requiring review."""

    __tablename__ = "audit_issues"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    issue_type: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="warning", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="open", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_source_block_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_blocks.id", ondelete="RESTRICT")
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class AuditEvent(Base):
    """Append-only history of audit decisions and edits."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    issue_id: Mapped[str | None] = mapped_column(
        ForeignKey("audit_issues.id", ondelete="RESTRICT")
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), default="system", nullable=False)
    before_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class Question(TimestampMixin, Base):
    """A review question grounded in one or more source blocks."""

    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint(
            "question_type IN ('fill_blank', 'single_choice', 'short_answer')",
            name="ck_question_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'needs_review', 'approved', 'rejected')",
            name="ck_question_status",
        ),
        CheckConstraint("difficulty IS NULL OR difficulty BETWEEN 1 AND 5",
                        name="ck_question_difficulty"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    knowledge_node_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_nodes.id", ondelete="RESTRICT")
    )
    question_type: Mapped[str] = mapped_column(String(24), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    answer: Mapped[dict[str, Any] | str] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str | None] = mapped_column(String(80))

    knowledge_node: Mapped[KnowledgeNode | None] = relationship(back_populates="questions")
    sources: Mapped[list[QuestionSource]] = relationship(back_populates="question")


class QuestionSource(Base):
    """Many-to-many evidence link between a question and a source block."""

    __tablename__ = "question_sources"

    question_id: Mapped[str] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), primary_key=True
    )
    source_block_id: Mapped[str] = mapped_column(
        ForeignKey("source_blocks.id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(40), default="answer_evidence", nullable=False)

    question: Mapped[Question] = relationship(back_populates="sources")
    source_block: Mapped[SourceBlock] = relationship()


class ReviewState(TimestampMixin, Base):
    """Scheduling state for a knowledge node or a question, scoped to a learner."""

    __tablename__ = "review_states"
    __table_args__ = (
        UniqueConstraint("learner_id", "target_type", "target_id", name="uq_review_target"),
        CheckConstraint("consecutive_correct >= 0", name="ck_review_correct_nonnegative"),
        CheckConstraint("interval_days >= 0", name="ck_review_interval_nonnegative"),
        CheckConstraint(
            "target_type IN ('knowledge_node', 'question')",
            name="ck_review_target_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    learner_id: Mapped[str] = mapped_column(String(120), default="default", nullable=False)
    target_type: Mapped[str] = mapped_column(String(24), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    consecutive_correct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    interval_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mastered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AnswerLog(Base):
    """Immutable record of a learner response or self-assessment."""

    __tablename__ = "answer_logs"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('knowledge_node', 'question')",
            name="ck_answer_target_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    review_state_id: Mapped[str | None] = mapped_column(
        ForeignKey("review_states.id", ondelete="RESTRICT")
    )
    question_id: Mapped[str | None] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT")
    )
    learner_id: Mapped[str] = mapped_column(String(120), default="default", nullable=False)
    target_type: Mapped[str] = mapped_column(String(24), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    response: Mapped[dict[str, Any] | str | None] = mapped_column(JSON)
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    interval_before_days: Mapped[int | None] = mapped_column(Integer)
    interval_after_days: Mapped[int | None] = mapped_column(Integer)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
