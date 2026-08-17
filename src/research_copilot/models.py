"""SQLAlchemy ORM models — the 9 scoped tables plus `paper_chunks`, reserved for
when full-text ingestion lands (not written to in v1).

`papers.id` and `authors.id` are OpenAlex IDs (e.g. "W2741809807"), used directly
as primary keys so re-fetching the same work/author is a natural upsert, not a dedupe step.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from research_copilot.config import EMBEDDING_DIM


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    google_sub: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String)
    avatar_url: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    learning_goals: Mapped[list["LearningGoal"]] = relationship(back_populates="user")
    collections: Mapped[list["Collection"]] = relationship(back_populates="user")


class LearningGoal(Base):
    __tablename__ = "learning_goals"
    __table_args__ = (
        CheckConstraint("target_level in ('beginner','intermediate','advanced')", name="ck_goal_level"),
        CheckConstraint("status in ('active','completed','archived')", name="ck_goal_status"),
        Index("ix_learning_goals_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    target_level: Mapped[str] = mapped_column(String, default="beginner")
    status: Mapped[str] = mapped_column(String, default="active")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="learning_goals")
    collections: Mapped[list["Collection"]] = relationship(back_populates="learning_goal")


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # OpenAlex Work ID
    doi: Mapped[str | None] = mapped_column(String)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    abstract: Mapped[str | None] = mapped_column(Text)
    publication_year: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(String)
    oa_status: Mapped[str | None] = mapped_column(String)
    oa_pdf_url: Mapped[str | None] = mapped_column(String)
    cited_by_count: Mapped[int] = mapped_column(Integer, default=0)
    topics: Mapped[dict | None] = mapped_column(JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    openalex_raw: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    authors: Mapped[list["PaperAuthor"]] = relationship(back_populates="paper", cascade="all, delete-orphan")


class Author(Base):
    __tablename__ = "authors"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # OpenAlex Author ID
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    orcid: Mapped[str | None] = mapped_column(String)
    institution_name: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    papers: Mapped[list["PaperAuthor"]] = relationship(back_populates="author")


class PaperAuthor(Base):
    __tablename__ = "paper_authors"
    __table_args__ = (Index("ix_paper_authors_author_id", "author_id"),)

    paper_id: Mapped[str] = mapped_column(String, ForeignKey("papers.id"), primary_key=True)
    author_id: Mapped[str] = mapped_column(String, ForeignKey("authors.id"), primary_key=True)
    author_position: Mapped[str | None] = mapped_column(String)  # 'first' | 'middle' | 'last'

    paper: Mapped["Paper"] = relationship(back_populates="authors")
    author: Mapped["Author"] = relationship(back_populates="papers")


class Collection(Base):
    __tablename__ = "collections"
    __table_args__ = (Index("ix_collections_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    learning_goal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("learning_goals.id"))
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="collections")
    learning_goal: Mapped["LearningGoal | None"] = relationship(back_populates="collections")
    papers: Mapped[list["CollectionPaper"]] = relationship(back_populates="collection", cascade="all, delete-orphan")


class CollectionPaper(Base):
    __tablename__ = "collection_papers"

    collection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("collections.id"), primary_key=True)
    paper_id: Mapped[str] = mapped_column(String, ForeignKey("papers.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    collection: Mapped["Collection"] = relationship(back_populates="papers")
    paper: Mapped["Paper"] = relationship()


class ReadingProgress(Base):
    __tablename__ = "reading_progress"
    __table_args__ = (
        CheckConstraint("status in ('not_started','in_progress','done')", name="ck_progress_status"),
        CheckConstraint("progress_pct >= 0 and progress_pct <= 100", name="ck_progress_pct_range"),
        UniqueConstraint("user_id", "paper_id", "collection_id", name="uq_progress_scope"),
        Index("ix_reading_progress_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    paper_id: Mapped[str] = mapped_column(String, ForeignKey("papers.id"), nullable=False)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("collections.id"))
    status: Mapped[str] = mapped_column(String, default="not_started")
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)  # 0-100; status is derived from this
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Note(Base):
    """Scoped to a paper, a collection, or both — at least one must be set.
    A paper-scoped note (paper_id set, collection_id null) is about that paper's content;
    a collection-scoped note (collection_id set, paper_id null) is about the topic as a whole.
    """

    __tablename__ = "notes"
    __table_args__ = (
        CheckConstraint("paper_id is not null or collection_id is not null", name="ck_notes_scoped"),
        Index("ix_notes_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    paper_id: Mapped[str | None] = mapped_column(String, ForeignKey("papers.id"))
    collection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("collections.id"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PaperChunk(Base):
    """Reserved for v1.1 full-text ingestion. Not written to in v1 — abstracts only."""

    __tablename__ = "paper_chunks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    paper_id: Mapped[str] = mapped_column(String, ForeignKey("papers.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))


# --- Study Buddy: a second, separate conversational mode alongside the workspace
# above, not a replacement for it. A concept card belongs to one learning goal;
# "papers"/"authors" above are reused as-is for the internal (never user-facing)
# evidence log — no duplicate paper cache needed.


class StudyConcept(Base):
    """One plain-language topic card in a learning goal's journey. User-scoped
    via learning_goal_id, not shared/cached like papers are — each user's
    journey through "how CRISPR works" is their own, even if the underlying
    papers are the same shared cache rows everyone else's search also hits."""

    __tablename__ = "study_concepts"
    __table_args__ = (
        CheckConstraint(
            "status in ('not_started','in_progress','understood','struggling')", name="ck_concept_status"
        ),
        Index("ix_study_concepts_learning_goal_id", "learning_goal_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    learning_goal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("learning_goals.id"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="not_started")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    explanations: Mapped[list["ConceptExplanation"]] = relationship(back_populates="concept", cascade="all, delete-orphan")
    evidence: Mapped[list["ConceptEvidence"]] = relationship(back_populates="concept", cascade="all, delete-orphan")
    checks: Mapped[list["ComprehensionCheck"]] = relationship(back_populates="concept", cascade="all, delete-orphan")


class ConceptExplanation(Base):
    """One generated explanation at one layer. `variant` increments each time
    "explain differently" is used, so past attempts stay around (useful for
    eval/debugging) instead of being overwritten."""

    __tablename__ = "concept_explanations"
    __table_args__ = (
        CheckConstraint("layer in (1,2,3)", name="ck_explanation_layer"),
        Index("ix_concept_explanations_concept_id", "concept_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("study_concepts.id"), nullable=False)
    layer: Mapped[int] = mapped_column(Integer, nullable=False)
    variant: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    reading_grade_level: Mapped[float | None] = mapped_column()  # Flesch-Kincaid grade, eval hook
    faithfulness_ok: Mapped[bool | None] = mapped_column()  # LLM-judge pass/fail, eval hook
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    concept: Mapped["StudyConcept"] = relationship(back_populates="explanations")


class ConceptEvidence(Base):
    """Internal evidence log — never shown directly; the citation chip in the UI
    is generated from this, and "where did this come from?" reads from it."""

    __tablename__ = "concept_evidence"
    __table_args__ = (Index("ix_concept_evidence_concept_id", "concept_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("study_concepts.id"), nullable=False)
    paper_id: Mapped[str] = mapped_column(String, ForeignKey("papers.id"), nullable=False)
    snippet: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    concept: Mapped["StudyConcept"] = relationship(back_populates="evidence")
    paper: Mapped["Paper"] = relationship()


class ComprehensionCheck(Base):
    """A lightweight "does this make sense?" signal per concept — the spec
    explicitly allows this simpler form instead of scored quiz questions;
    that's the v1 here. `understood=False` is the signal to re-explain simpler
    or insert a prerequisite, not to show a harder paper."""

    __tablename__ = "comprehension_checks"
    __table_args__ = (Index("ix_comprehension_checks_concept_id", "concept_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("study_concepts.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    understood: Mapped[bool | None] = mapped_column()  # null until answered
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    concept: Mapped["StudyConcept"] = relationship(back_populates="checks")
