"""Rule-based textbook outline extraction and auditable manual correction."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ruangao_note.domain.models import (
    AuditEvent,
    AuditIssue,
    Chapter,
    Section,
    SourceBlock,
)

_DOTTED_NUMBER = re.compile(
    r"^(?P<number>\d+(?:\.\d+)+)\s*[、．.]?\s*(?P<title>.+)$"
)
_BARE_NUMBER = re.compile(r"^(?P<number>\d+)\s*[、．.]\s*(?P<title>.+)$")
_CHINESE_SECTION = re.compile(
    r"^(?P<number>第[一二三四五六七八九十百]+[节部分篇])\s*(?P<title>.*)$"
)
_CHAPTER_TITLE = re.compile(r"^\s*第\s*\d+\s*[章节篇部]")


class TOCNotFoundError(LookupError):
    """Raised when a requested chapter or section does not exist."""


class TOCValidationError(ValueError):
    """Raised when a manual outline correction violates tree invariants."""


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", value).strip()


def _heading_kind(text: str) -> tuple[str, str | None, str, int | None]:
    """Return numbering kind, section number, display title, and explicit depth."""
    value = text.strip()
    dotted = _DOTTED_NUMBER.match(value)
    if dotted:
        number = dotted.group("number")
        return "dotted", number, dotted.group("title").strip(), len(number.split(".")) - 1

    bare = _BARE_NUMBER.match(value)
    if bare:
        number = bare.group("number")
        return "bare", number, bare.group("title").strip(), None

    chinese = _CHINESE_SECTION.match(value)
    if chinese:
        return (
            "chinese",
            chinese.group("number"),
            chinese.group("title").strip() or value,
            1,
        )

    return "unclassified", None, value, None


def _is_chapter_heading(text: str, chapter: Chapter) -> bool:
    compact = _normalized(text)
    chapter_title = _normalized(chapter.title)
    return bool(_CHAPTER_TITLE.match(text)) or compact == chapter_title


def _section_data(section: Section) -> dict[str, Any]:
    return {
        "id": section.id,
        "chapter_id": section.chapter_id,
        "parent_id": section.parent_id,
        "title": section.title,
        "section_number": section.section_number,
        "level": section.level,
        "sort_order": section.sort_order,
        "source_block_id": section.source_block_id,
    }


def _record_issue(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    issue_type: str,
    message: str,
    severity: str = "warning",
    source_block_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditIssue:
    existing = session.scalar(
        select(AuditIssue).where(
            AuditIssue.entity_type == entity_type,
            AuditIssue.entity_id == entity_id,
            AuditIssue.issue_type == issue_type,
            AuditIssue.status == "open",
        )
    )
    if existing is not None:
        if details:
            existing.details = {**(existing.details or {}), **details}
        return existing
    issue = AuditIssue(
        entity_type=entity_type,
        entity_id=entity_id,
        issue_type=issue_type,
        severity=severity,
        status="open",
        message=message,
        evidence_source_block_id=source_block_id,
        details=details or {},
    )
    session.add(issue)
    session.flush()
    return issue


class TOCService:
    """Extract numbered outline candidates from heading evidence blocks.

    Deterministic rules are used instead of an LLM. Ordinary paragraphs are never
    converted into sections. Every generated Section points back to its heading
    SourceBlock, while ambiguous headings are retained with an open AuditIssue.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def generate(self, chapter_id: str) -> dict[str, Any]:
        chapter = self.session.get(Chapter, chapter_id)
        if chapter is None:
            raise TOCNotFoundError("Chapter not found.")

        headings = self.session.scalars(
            select(SourceBlock)
            .where(
                SourceBlock.chapter_id == chapter_id,
                SourceBlock.block_type == "heading",
                SourceBlock.is_active.is_(True),
            )
            .order_by(SourceBlock.sort_order, SourceBlock.id)
        ).all()
        existing_sections = self.session.scalars(
            select(Section)
            .where(Section.chapter_id == chapter_id)
            .order_by(Section.sort_order, Section.id)
        ).all()
        sections_by_source = {
            section.source_block_id: section
            for section in existing_sections
            if section.source_block_id
        }
        sections_by_number: dict[str, list[Section]] = defaultdict(list)
        for section in existing_sections:
            if section.section_number:
                sections_by_number[section.section_number].append(section)

        next_order: dict[str | None, int] = {}
        for section in existing_sections:
            parent_key = section.parent_id
            next_order[parent_key] = max(
                next_order.get(parent_key, 0), section.sort_order + 1
            )

        created: list[Section] = []
        issue_ids: set[str] = set()
        skipped_chapter_heading = 0
        already_linked = 0
        empty_heading_count = 0
        previous_section: Section | None = None
        previous_dotted_section: Section | None = None

        for block in headings:
            text = (block.text or "").strip()
            if not text:
                empty_heading_count += 1
                issue = _record_issue(
                    self.session,
                    entity_type="source_block",
                    entity_id=block.id,
                    issue_type="empty_heading_text",
                    message="版面分析将此块识别为标题，但没有提取到标题文字。",
                    severity="error",
                    source_block_id=block.id,
                    details={"block_key": block.block_key, "sort_order": block.sort_order},
                )
                issue_ids.add(issue.id)
                continue

            if _is_chapter_heading(text, chapter):
                skipped_chapter_heading += 1
                continue

            existing = sections_by_source.get(block.id)
            kind, number, title, explicit_level = _heading_kind(text)
            if existing is not None:
                already_linked += 1
                previous_section = existing
                if kind == "dotted":
                    previous_dotted_section = existing
                continue

            title = title or text
            parent: Section | None = None
            level: int
            issue_specs: list[tuple[str, str, str]] = []

            if kind == "dotted":
                assert number is not None and explicit_level is not None
                parts = number.split(".")
                level = explicit_level
                for length in range(len(parts) - 1, 1, -1):
                    ancestor_number = ".".join(parts[:length])
                    candidates = sections_by_number.get(ancestor_number, [])
                    if candidates:
                        parent = candidates[-1]
                        break
                if level > 1 and parent is None:
                    issue_specs.append(
                        (
                            "missing_parent_section",
                            "缺少编号父级目录，当前标题暂时作为根节点保存。",
                            "warning",
                        )
                    )
                elif parent is not None and level > parent.level + 1:
                    issue_specs.append(
                        (
                            "section_level_jump",
                            "标题编号显示的层级跨过了一个或多个目录层级。",
                            "warning",
                        )
                    )
                previous_dotted_section = None
            elif kind == "bare":
                parent = previous_dotted_section or previous_section
                level = parent.level + 1 if parent is not None else 1
                if parent is None:
                    issue_specs.append(
                        (
                            "unclassified_heading_level",
                            "该标题只有单级编号，前文没有明确父级，目录层级需要人工确认。",
                            "warning",
                        )
                    )
            elif kind == "chinese":
                parent = previous_section
                level = 1 if parent is None else parent.level + 1
            else:
                parent = previous_section
                level = 1 if parent is None else parent.level + 1
                issue_specs.append(
                    (
                        "unclassified_heading_level",
                        "该标题没有可识别的编号，系统按上下文暂定层级，请人工确认。",
                        "warning",
                    )
                )

            parent_id = parent.id if parent is not None else None
            sort_order = next_order.get(parent_id, 0)
            next_order[parent_id] = sort_order + 1
            section = Section(
                chapter_id=chapter_id,
                parent_id=parent_id,
                title=title,
                section_number=number,
                level=level,
                sort_order=sort_order,
                source_block_id=block.id,
            )
            self.session.add(section)
            self.session.flush()
            created.append(section)
            sections_by_source[block.id] = section
            if number:
                sections_by_number[number].append(section)
            previous_section = section
            if kind == "dotted":
                previous_dotted_section = section

            self.session.add(
                AuditEvent(
                    entity_type="section",
                    entity_id=section.id,
                    action="toc_auto_generated",
                    actor="system",
                    after_data={
                        **_section_data(section),
                        "source_block_key": block.block_key,
                    },
                    reason="TP-06 deterministic heading-number and layout-context rules",
                )
            )
            for issue_type, message, severity in issue_specs:
                issue = _record_issue(
                    self.session,
                    entity_type="section",
                    entity_id=section.id,
                    issue_type=issue_type,
                    message=message,
                    severity=severity,
                    source_block_id=block.id,
                    details={
                        "section_number": number,
                        "inferred_level": level,
                        "parent_id": parent_id,
                        "source_block_key": block.block_key,
                    },
                )
                issue_ids.add(issue.id)

        # Detect duplicate sibling numbers/titles without changing or discarding nodes.
        sibling_groups: dict[str | None, list[Section]] = defaultdict(list)
        all_sections = self.session.scalars(
            select(Section).where(Section.chapter_id == chapter_id)
        ).all()
        for section in all_sections:
            sibling_groups[section.parent_id].append(section)

        for siblings in sibling_groups.values():
            number_groups: dict[str, list[Section]] = defaultdict(list)
            title_groups: dict[str, list[Section]] = defaultdict(list)
            dotted_groups: dict[str, list[tuple[int, Section]]] = defaultdict(list)
            bare_groups: dict[int, list[Section]] = defaultdict(list)
            for section in siblings:
                if section.section_number:
                    number_groups[section.section_number].append(section)
                    parts = section.section_number.split(".")
                    if len(parts) > 1 and all(part.isdigit() for part in parts):
                        dotted_groups[".".join(parts[:-1])].append(
                            (int(parts[-1]), section)
                        )
                    elif section.section_number.isdigit():
                        bare_groups[int(section.section_number)].append(section)
                title_groups[_normalized(section.title)].append(section)

            for duplicate_group in number_groups.values():
                if len(duplicate_group) > 1:
                    for section in duplicate_group:
                        issue = _record_issue(
                            self.session,
                            entity_type="section",
                            entity_id=section.id,
                            issue_type="duplicate_section_number",
                            message="同一父级目录下存在重复编号。",
                            source_block_id=section.source_block_id,
                            details={
                                "section_number": section.section_number,
                                "sibling_ids": [item.id for item in duplicate_group],
                            },
                        )
                        issue_ids.add(issue.id)
            for duplicate_group in title_groups.values():
                if len(duplicate_group) > 1:
                    for section in duplicate_group:
                        issue = _record_issue(
                            self.session,
                            entity_type="section",
                            entity_id=section.id,
                            issue_type="duplicate_section_title",
                            message="同一父级目录下存在重复标题。",
                            source_block_id=section.source_block_id,
                            details={"sibling_ids": [item.id for item in duplicate_group]},
                        )
                        issue_ids.add(issue.id)

            for prefix, values in dotted_groups.items():
                numbers = sorted({number for number, _ in values})
                if len(numbers) >= 2 and numbers[-1] - numbers[0] + 1 > len(numbers):
                    missing = sorted(set(range(numbers[0], numbers[-1] + 1)) - set(numbers))
                    issue = _record_issue(
                        self.session,
                        entity_type="chapter",
                        entity_id=chapter_id,
                        issue_type="section_numbering_gap",
                        message="同一编号父级下存在不连续的小节编号，请核对是否漏识别标题。",
                        details={
                            "parent_number_prefix": prefix,
                            "present_numbers": numbers,
                            "missing_numbers": missing,
                            "sibling_ids": [section.id for _, section in values],
                        },
                    )
                    issue_ids.add(issue.id)
            if bare_groups:
                numbers = sorted(bare_groups)
                if len(numbers) >= 2 and numbers[-1] - numbers[0] + 1 > len(numbers):
                    missing = sorted(set(range(numbers[0], numbers[-1] + 1)) - set(numbers))
                    issue = _record_issue(
                        self.session,
                        entity_type="chapter",
                        entity_id=chapter_id,
                        issue_type="section_numbering_gap",
                        message="同一父级目录下存在不连续的数字标题，请核对是否漏识别。",
                        details={
                            "parent_section_id": siblings[0].parent_id,
                            "present_numbers": numbers,
                            "missing_numbers": missing,
                            "sibling_ids": [
                                section.id for items in bare_groups.values() for section in items
                            ],
                        },
                    )
                    issue_ids.add(issue.id)

        if empty_heading_count:
            issue_ids.update(
                issue.id
                for issue in self.session.scalars(
                    select(AuditIssue).where(
                        AuditIssue.entity_type == "source_block",
                        AuditIssue.issue_type == "empty_heading_text",
                        AuditIssue.status == "open",
                        AuditIssue.entity_id.in_(
                            [block.id for block in headings if not (block.text or "").strip()]
                        ),
                    )
                ).all()
            )

        self.session.flush()
        return {
            "chapter_id": chapter_id,
            "source_heading_count": len(headings),
            "created_count": len(created),
            "already_linked_count": already_linked,
            "skipped_chapter_heading_count": skipped_chapter_heading,
            "empty_heading_count": empty_heading_count,
            "section_count": len(all_sections),
            "created_section_ids": [section.id for section in created],
            "issue_count": len(issue_ids),
            "issue_ids": sorted(issue_ids),
            "message": (
                f"读取 {len(headings)} 个标题块，新建 {len(created)} 个目录节点；"
                f"已关联 {already_linked} 个，跳过章节总标题 {skipped_chapter_heading} 个。"
            ),
        }

    def list_sections(self, chapter_id: str) -> dict[str, Any]:
        chapter = self.session.get(Chapter, chapter_id)
        if chapter is None:
            raise TOCNotFoundError("Chapter not found.")
        sections = self.session.scalars(
            select(Section)
            .options(selectinload(Section.source_block))
            .where(Section.chapter_id == chapter_id)
            .order_by(Section.sort_order, Section.id)
        ).all()
        section_ids = [section.id for section in sections]
        heading_source_ids = self.session.scalars(
            select(SourceBlock.id).where(
                SourceBlock.chapter_id == chapter_id,
                SourceBlock.block_type == "heading",
            )
        ).all()
        conditions = [
            (AuditIssue.entity_type == "chapter") & (AuditIssue.entity_id == chapter_id),
            (AuditIssue.entity_type == "section")
            & (AuditIssue.entity_id.in_(section_ids or ["__none__"])),
            (AuditIssue.entity_type == "source_block")
            & (
                AuditIssue.entity_id.in_(heading_source_ids or ["__none__"])
            ),
        ]
        issues = self.session.scalars(
            select(AuditIssue)
            .where(AuditIssue.status == "open", conditions[0] | conditions[1] | conditions[2])
            .order_by(AuditIssue.created_at, AuditIssue.id)
        ).all()
        return {
            "chapter_id": chapter_id,
            "count": len(sections),
            "items": [
                {
                    **_section_data(section),
                    "source_text": (
                        section.source_block.text if section.source_block else None
                    ),
                    "page_id": (
                        section.source_block.page_id if section.source_block else None
                    ),
                    "image_url": (
                        f"/api/chapters/{chapter_id}/pages/"
                        f"{section.source_block.page_id}/image"
                        if section.source_block
                        else None
                    ),
                    "bbox": section.source_block.bbox if section.source_block else None,
                }
                for section in sections
            ],
            "issues": [
                {
                    "id": issue.id,
                    "entity_type": issue.entity_type,
                    "entity_id": issue.entity_id,
                    "issue_type": issue.issue_type,
                    "severity": issue.severity,
                    "message": issue.message,
                    "evidence_source_block_id": issue.evidence_source_block_id,
                    "details": issue.details or {},
                }
                for issue in issues
            ],
            "history": [
                {
                    "id": event.id,
                    "entity_id": event.entity_id,
                    "action": event.action,
                    "actor": event.actor,
                    "before_data": event.before_data,
                    "after_data": event.after_data,
                    "reason": event.reason,
                    "created_at": event.created_at.isoformat(),
                }
                for event in self.session.scalars(
                    select(AuditEvent)
                    .where(
                        AuditEvent.entity_type == "section",
                        AuditEvent.entity_id.in_(section_ids or ["__none__"]),
                    )
                    .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
                    .limit(100)
                ).all()
            ],
        }

    def update_section(
        self,
        chapter_id: str,
        section_id: str,
        changes: dict[str, Any],
        *,
        actor: str = "user",
        reason: str | None = None,
    ) -> Section:
        if self.session.get(Chapter, chapter_id) is None:
            raise TOCNotFoundError("Chapter not found.")
        section = self.session.scalar(
            select(Section).where(
                Section.id == section_id,
                Section.chapter_id == chapter_id,
            )
        )
        if section is None:
            raise TOCNotFoundError("Section not found in this chapter.")

        allowed = {"title", "section_number", "level", "parent_id", "sort_order"}
        if not changes or not set(changes).issubset(allowed):
            raise TOCValidationError("At least one valid section field must be supplied.")

        before = _section_data(section)
        candidate_parent_id = changes.get("parent_id", section.parent_id)
        parent: Section | None = None
        if candidate_parent_id is not None:
            parent = self.session.scalar(
                select(Section).where(
                    Section.id == candidate_parent_id,
                    Section.chapter_id == chapter_id,
                )
            )
            if parent is None:
                raise TOCValidationError("Parent section must belong to the same chapter.")
            cursor: Section | None = parent
            while cursor is not None:
                if cursor.id == section.id:
                    raise TOCValidationError("A section cannot be its own ancestor.")
                cursor = (
                    self.session.get(Section, cursor.parent_id)
                    if cursor.parent_id
                    else None
                )

        new_title = changes.get("title", section.title)
        if not isinstance(new_title, str) or not new_title.strip():
            raise TOCValidationError("Section title must not be empty.")
        new_level = changes.get("level", section.level)
        if not isinstance(new_level, int) or isinstance(new_level, bool) or new_level < 1:
            raise TOCValidationError("Section level must be a positive integer.")
        if parent is not None and parent.level >= new_level:
            raise TOCValidationError("Child section level must be deeper than its parent.")
        new_sort_order = changes.get("sort_order", section.sort_order)
        if (
            not isinstance(new_sort_order, int)
            or isinstance(new_sort_order, bool)
            or new_sort_order < 0
        ):
            raise TOCValidationError("Section sort_order must be a non-negative integer.")
        new_number = changes.get("section_number", section.section_number)
        if new_number is not None and (
            not isinstance(new_number, str) or len(new_number) > 80
        ):
            raise TOCValidationError("Section number must be at most 80 characters.")

        section.title = new_title.strip()
        section.section_number = new_number.strip() if new_number else None
        section.level = new_level
        section.parent_id = candidate_parent_id
        section.sort_order = new_sort_order
        self.session.flush()

        after = _section_data(section)
        self.session.add(
            AuditEvent(
                entity_type="section",
                entity_id=section.id,
                action="toc_manual_updated",
                actor=actor[:120],
                before_data=before,
                after_data=after,
                reason=(reason or "人工修正目录结构")[:1000],
            )
        )

        resolved_types = set()
        if "title" in changes:
            resolved_types.add("duplicate_section_title")
        if "section_number" in changes:
            resolved_types.update(
                {"duplicate_section_number", "toc_heading_without_number"}
            )
        if "level" in changes or "parent_id" in changes:
            resolved_types.update(
                {
                    "missing_parent_section",
                    "section_level_jump",
                    "unclassified_heading_level",
                }
            )
        if resolved_types:
            issues = self.session.scalars(
                select(AuditIssue).where(
                    AuditIssue.entity_type == "section",
                    AuditIssue.entity_id == section.id,
                    AuditIssue.status == "open",
                    AuditIssue.issue_type.in_(resolved_types),
                )
            ).all()
            for issue in issues:
                issue.status = "resolved"
                self.session.add(
                    AuditEvent(
                        issue_id=issue.id,
                        entity_type="section",
                        entity_id=section.id,
                        action="audit_issue_resolved",
                        actor=actor[:120],
                        before_data={"status": "open"},
                        after_data={"status": "resolved", "section": after},
                        reason=(reason or "人工修正后解决目录问题")[:1000],
                    )
                )

        self.session.flush()
        return section
