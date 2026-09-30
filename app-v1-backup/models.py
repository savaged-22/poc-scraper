from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SearchStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    portals: list[str] | None = None


class ScrapingTask(BaseModel):
    task_id: str
    search_id: str

    query: str
    portal: str

    status: TaskStatus = TaskStatus.PENDING

    attempt: int = 0

    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    result: dict[str, Any] | None = None
    error: str | None = None


class SearchJob(BaseModel):
    search_id: str

    query: str

    status: SearchStatus = SearchStatus.CREATED

    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    total_tasks: int = 0
    completed_tasks: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0

    tasks: list[str] = Field(default_factory=list)