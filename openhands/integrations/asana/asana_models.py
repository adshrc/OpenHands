"""Pydantic models for Asana API data."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AsanaResource(BaseModel):
    """Base Asana resource with GID."""

    gid: str
    resource_type: str | None = None
    name: str | None = None  # Often returned by API


class AsanaUser(AsanaResource):
    """Asana user representation."""

    name: str | None = None
    email: str | None = None


class AsanaProject(AsanaResource):
    """Asana project representation."""

    name: str | None = None


class AsanaWorkspace(AsanaResource):
    """Asana workspace representation."""

    name: str | None = None


class AsanaTask(AsanaResource):
    """Asana task representation."""

    name: str
    notes: str | None = None
    html_notes: str | None = None
    completed: bool = False
    completed_at: datetime | None = None
    due_on: str | None = None
    due_at: datetime | None = None
    assignee: AsanaUser | None = None
    projects: list[AsanaProject] = Field(default_factory=list)
    workspace: AsanaWorkspace | None = None
    custom_fields: list[dict[str, Any]] = Field(default_factory=list)
    permalink_url: str | None = None
    created_at: datetime | None = None
    modified_at: datetime | None = None
    parent: 'AsanaTask | None' = None
    tags: list[dict[str, Any]] = Field(default_factory=list)


class WebhookEvent(BaseModel):
    """Individual webhook event."""

    user: AsanaUser | None = None
    created_at: datetime | None = None
    action: str  # added, changed, deleted, removed, undeleted
    resource: AsanaResource
    parent: AsanaResource | None = None
    change: dict[str, Any] | None = None


class WebhookPayload(BaseModel):
    """Webhook payload containing events."""

    events: list[WebhookEvent] = Field(default_factory=list)


class WebhookFilter(BaseModel):
    """Filter for webhook events."""

    resource_type: str
    resource_subtype: str | None = None
    action: str | None = None
    fields: list[str] | None = None


class WebhookCreateRequest(BaseModel):
    """Request body for creating a webhook."""

    resource: str  # GID of the resource to watch
    target: str  # URL to receive webhook events
    filters: list[WebhookFilter] | None = None


class Webhook(AsanaResource):
    """Asana webhook representation."""

    active: bool
    resource: AsanaResource
    target: str
    created_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_failure_content: str | None = None
    last_success_at: datetime | None = None
    filters: list[WebhookFilter] = Field(default_factory=list)


class StoryCreateRequest(BaseModel):
    """Request body for creating a story (comment) on a task."""

    text: str | None = None
    html_text: str | None = None
    is_pinned: bool = False


class Story(AsanaResource):
    """Asana story (comment/activity) representation."""

    text: str | None = None
    html_text: str | None = None
    type: str | None = None  # comment, system
    resource_subtype: str | None = None  # comment_added, etc.
    created_at: datetime | None = None
    created_by: AsanaUser | None = None
    is_pinned: bool = False
    target: AsanaResource | None = None  # The parent task/project


class TaskUpdateRequest(BaseModel):
    """Request body for updating a task."""

    completed: bool | None = None
    name: str | None = None
    notes: str | None = None
    assignee: str | None = None  # User GID
    due_on: str | None = None
    due_at: str | None = None
    custom_fields: dict[str, Any] | None = None
    liked: bool | None = None  # True to like the task, False to unlike


class StoryUpdateRequest(BaseModel):
    """Request body for updating a story (comment)."""

    text: str | None = None
    html_text: str | None = None
    is_pinned: bool | None = None
    liked: bool | None = None  # True to like the story, False to unlike
