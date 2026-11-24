from datetime import datetime, timezone

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    """リポジトリ一覧の項目

    display_nameは画面の表示名（日本語名）、descriptionは何をするPJかの説明。
    いずれも空の場合は、表示名をcore/repo_catalog.pyの辞書または登録名で補う。
    removedは一覧から削除済みかを表す。
    履歴（MR・CLI・Idea等）を残すため、行は消さずに一覧・同期の対象から外す。
    """

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    github_repo: Mapped[str]
    repo_path: Mapped[str]
    default_branch: Mapped[str]
    display_name: Mapped[str] = mapped_column(default="")
    description: Mapped[str] = mapped_column(default="")
    removed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class TaskCache(Base):
    __tablename__ = "tasks_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    github_issue_number: Mapped[int]
    title: Mapped[str]
    state_label: Mapped[str]
    synced_at: Mapped[datetime] = mapped_column(default=_now)


class Subtask(Base):
    __tablename__ = "subtasks"
    __table_args__ = (
        UniqueConstraint("project_id", "github_issue_number", "branch_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    github_issue_number: Mapped[int]
    title: Mapped[str]
    instruction: Mapped[str]
    branch_name: Mapped[str]
    github_pr_number: Mapped[int | None] = mapped_column(default=None)
    lifecycle_state: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class ExecutionJob(Base):
    __tablename__ = "execution_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    subtask_id: Mapped[int] = mapped_column(ForeignKey("subtasks.id"))
    status: Mapped[str]
    queued_at: Mapped[datetime] = mapped_column(default=_now)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    ended_at: Mapped[datetime | None] = mapped_column(default=None)
    exit_code: Mapped[int | None] = mapped_column(default=None)
    claude_session_id: Mapped[str | None] = mapped_column(default=None)
    error_message: Mapped[str | None] = mapped_column(default=None)
    worker_id: Mapped[int | None] = mapped_column(default=None)
    claimed_at: Mapped[datetime | None] = mapped_column(default=None)
    heartbeat_at: Mapped[datetime | None] = mapped_column(default=None)


class MergeJob(Base):
    """MRのマージ待ち行列

    マージは1件ずつ順に処理する。
    """

    __tablename__ = "merge_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    subtask_id: Mapped[int] = mapped_column(ForeignKey("subtasks.id"))
    status: Mapped[str]
    queued_at: Mapped[datetime] = mapped_column(default=_now)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    ended_at: Mapped[datetime | None] = mapped_column(default=None)
    error_message: Mapped[str | None] = mapped_column(default=None)


class ExecutionEvent(Base):
    __tablename__ = "execution_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("execution_jobs.id"))
    sequence_no: Mapped[int]
    event_type: Mapped[str]
    content: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=_now)


class CliSession(Base):
    """リポジトリ表示のCLIタブの項目（対話）

    1対話を1行とし、Claudeのセッションを引き継いで続けて会話する。
    statusは応答中か、stateは一覧のOpen・Closeを表す。
    """

    __tablename__ = "cli_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    title: Mapped[str] = mapped_column(default="")
    state: Mapped[str] = mapped_column(default="open")
    status: Mapped[str]
    claude_session_id: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class CliMessage(Base):
    """CLIタブの項目に表示する発言"""

    __tablename__ = "cli_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    cli_session_id: Mapped[int] = mapped_column(ForeignKey("cli_sessions.id"))
    role: Mapped[str]
    content: Mapped[str]
    # 利用者の発言に添付したファイル（ID・ファイル名・画像かどうかのJSON配列）
    attachments: Mapped[str] = mapped_column(default="[]")
    created_at: Mapped[datetime] = mapped_column(default=_now)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("execution_jobs.id"))
    html_path: Mapped[str]
    summary: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=_now)


class IdeaSession(Base):
    """リポジトリ表示のIdeaタブの項目

    項目ごとにアイデア出しを実行し、提案を確認する。
    stateは一覧のOpen・Closeを表す。
    """

    __tablename__ = "idea_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    title: Mapped[str]
    state: Mapped[str] = mapped_column(default="open")
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class IdeaJob(Base):
    """アイデアマンのアイデア出しジョブ

    実行ジョブと同じワーカープールで処理する。
    対象リポジトリを読み取り専用で調査し、提案をideasに保存する。
    focusは依頼時に人間が指定した、アイデアを出してほしい観点（空なら指定なし）。
    """

    __tablename__ = "idea_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    idea_session_id: Mapped[int | None] = mapped_column(ForeignKey("idea_sessions.id"), default=None)
    status: Mapped[str]
    focus: Mapped[str] = mapped_column(default="")
    queued_at: Mapped[datetime] = mapped_column(default=_now)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    ended_at: Mapped[datetime | None] = mapped_column(default=None)
    worker_id: Mapped[int | None] = mapped_column(default=None)
    heartbeat_at: Mapped[datetime | None] = mapped_column(default=None)
    claude_session_id: Mapped[str | None] = mapped_column(default=None)
    result_summary: Mapped[str | None] = mapped_column(default=None)
    error_message: Mapped[str | None] = mapped_column(default=None)


class Idea(Base):
    """アイデアマンの提案

    GitHubへは書き込まず、人間が承認するまでアプリ内に保留する。
    """

    __tablename__ = "ideas"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    source_job_id: Mapped[int] = mapped_column(ForeignKey("idea_jobs.id"))
    category: Mapped[str]
    title: Mapped[str]
    summary: Mapped[str]
    detail: Mapped[str]
    rationale: Mapped[str]
    related_files: Mapped[str]
    related_issue_number: Mapped[int | None] = mapped_column(default=None)
    status: Mapped[str]
    reject_reason: Mapped[str | None] = mapped_column(default=None)
    created_issue_number: Mapped[int | None] = mapped_column(default=None)
    created_subtask_id: Mapped[int | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(default=None)


class RateLimitSnapshot(Base):
    """Claudeのレート制限の最新状況

    レート制限の枠（5時間・7日など）ごとに1行を持ち、受信のたびに上書きする。
    """

    __tablename__ = "rate_limit_snapshots"

    rate_limit_type: Mapped[str] = mapped_column(primary_key=True)
    status: Mapped[str]
    utilization: Mapped[float | None] = mapped_column(default=None)
    resets_at: Mapped[int | None] = mapped_column(default=None)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_identifier: Mapped[str]
    state: Mapped[str]
    heartbeat_at: Mapped[datetime] = mapped_column(default=_now)
    current_job_id: Mapped[int | None] = mapped_column(default=None)
