"""Asana API client."""

from typing import Any

import httpx

from openhands.core.logger import openhands_logger as logger
from openhands.integrations.asana.asana_models import (
    AsanaTask,
    Story,
    StoryCreateRequest,
    StoryUpdateRequest,
    TaskUpdateRequest,
    Webhook,
    WebhookCreateRequest,
)


class AsanaClient:
    """Async client for Asana API."""

    ASANA_API_BASE_URL = 'https://app.asana.com/api/1.0'

    def __init__(self, access_token: str, workspace_gid: str | None = None):
        """Initialize Asana client.

        Args:
            access_token: Asana Personal Access Token
            workspace_gid: Optional workspace GID for workspace-scoped operations
        """
        self.access_token = access_token
        self.workspace_gid = workspace_gid
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> 'AsanaClient':
        """Enter async context."""
        self._client = httpx.AsyncClient(
            base_url=self.ASANA_API_BASE_URL,
            headers={
                'Authorization': f'Bearer {self.access_token}',
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            },
            timeout=30.0,
        )
        return self

    async def __aexit__(
        self, exc_type: type | None, exc_val: Exception | None, exc_tb: Any
    ) -> None:
        """Exit async context."""
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        """Get the HTTP client."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")
        return self._client

    async def get_task(self, task_gid: str) -> AsanaTask:
        """Get a task by GID."""
        logger.debug(f'Fetching task {task_gid}')
        response = await self.client.get(
            f'/tasks/{task_gid}',
            params={
                'opt_fields': ','.join(
                    [
                        'gid',
                        'resource_type',
                        'name',
                        'notes',
                        'html_notes',
                        'completed',
                        'completed_at',
                        'due_on',
                        'due_at',
                        'assignee',
                        'assignee.gid',
                        'assignee.name',
                        'assignee.email',
                        'projects',
                        'projects.gid',
                        'projects.name',
                        'workspace',
                        'workspace.gid',
                        'workspace.name',
                        'custom_fields',
                        'permalink_url',
                        'created_at',
                        'modified_at',
                        'parent',
                        'tags',
                    ]
                )
            },
        )
        response.raise_for_status()
        data = response.json()['data']
        return AsanaTask(**data)

    async def update_task(
        self, task_gid: str, update: TaskUpdateRequest
    ) -> AsanaTask:
        """Update a task."""
        logger.info(f'Updating task {task_gid}')
        response = await self.client.put(
            f'/tasks/{task_gid}',
            json={'data': update.model_dump(exclude_none=True)},
        )
        response.raise_for_status()
        data = response.json()['data']
        return AsanaTask(**data)

    async def complete_task(self, task_gid: str) -> AsanaTask:
        """Mark a task as complete."""
        return await self.update_task(task_gid, TaskUpdateRequest(completed=True))

    async def like_task(self, task_gid: str) -> AsanaTask:
        """Like a task (add a heart/thumbs up)."""
        logger.info(f'Liking task {task_gid}')
        return await self.update_task(task_gid, TaskUpdateRequest(liked=True))

    async def add_comment(
        self,
        task_gid: str,
        text: str | None = None,
        html_text: str | None = None,
        is_pinned: bool = False,
    ) -> Story:
        """Add a comment to a task.

        Args:
            task_gid: The task GID to add comment to
            text: Plain text comment (mutually exclusive with html_text)
            html_text: HTML formatted comment wrapped in <body> tags
            is_pinned: Whether to pin the comment
        """
        if html_text:
            logger.info(
                f'Adding HTML comment to task {task_gid}, length={len(html_text)}'
            )
            request = StoryCreateRequest(html_text=html_text, is_pinned=is_pinned)
        else:
            logger.info(
                f'Adding comment to task {task_gid}, length={len(text or "")}'
            )
            request = StoryCreateRequest(text=text, is_pinned=is_pinned)

        payload = {'data': request.model_dump(exclude_none=True)}
        logger.info(f'Asana story create payload: {payload}')

        response = await self.client.post(
            f'/tasks/{task_gid}/stories',
            json=payload,
        )
        response.raise_for_status()
        data = response.json()['data']
        logger.info(f'Asana story create response: {data}')
        return Story(**data)

    async def get_story(self, story_gid: str) -> Story:
        """Get a story (comment) by GID."""
        logger.debug(f'Fetching story {story_gid}')
        response = await self.client.get(
            f'/stories/{story_gid}',
            params={
                'opt_fields': ','.join(
                    [
                        'text',
                        'html_text',
                        'type',
                        'resource_subtype',
                        'created_at',
                        'created_by',
                        'created_by.name',
                        'is_pinned',
                        'target',
                        'target.gid',
                        'target.name',
                    ]
                )
            },
        )
        response.raise_for_status()
        data = response.json()['data']
        return Story(**data)

    async def get_task_stories(self, task_gid: str) -> list[Story]:
        """Get all stories (comments and activity) for a task.

        Args:
            task_gid: The task GID to get stories for

        Returns:
            List of Story objects, ordered by creation time (oldest first)
        """
        logger.debug(f'Fetching stories for task {task_gid}')
        response = await self.client.get(
            f'/tasks/{task_gid}/stories',
            params={
                'opt_fields': ','.join(
                    [
                        'text',
                        'html_text',
                        'type',
                        'resource_subtype',
                        'created_at',
                        'created_by',
                        'created_by.name',
                        'is_pinned',
                    ]
                )
            },
        )
        response.raise_for_status()
        data = response.json()['data']
        return [Story(**s) for s in data]

    async def update_story(
        self, story_gid: str, update: StoryUpdateRequest
    ) -> Story:
        """Update a story (comment)."""
        logger.info(f'Updating story {story_gid}')
        response = await self.client.put(
            f'/stories/{story_gid}',
            json={'data': update.model_dump(exclude_none=True)},
        )
        response.raise_for_status()
        data = response.json()['data']
        return Story(**data)

    async def like_story(self, story_gid: str) -> Story:
        """Like a story (comment).

        Note: This may not work if the Asana API doesn't support setting liked via PUT.
        If it fails, we'll fall back to not acknowledging comments with likes.
        """
        logger.info(f'Liking story {story_gid}')
        return await self.update_story(story_gid, StoryUpdateRequest(liked=True))

    async def get_webhooks(self, workspace_gid: str | None = None) -> list[Webhook]:
        """Get all webhooks for a workspace."""
        workspace = workspace_gid or self.workspace_gid
        if not workspace:
            raise ValueError('workspace_gid is required')

        logger.debug(f'Fetching webhooks for workspace {workspace}')
        response = await self.client.get(
            '/webhooks',
            params={
                'workspace': workspace,
                'opt_fields': 'active,resource,resource.name,target,created_at,last_failure_at,last_failure_content,last_success_at,filters,filters.action,filters.resource_type,filters.fields',
            },
        )
        response.raise_for_status()
        data = response.json()['data']
        return [Webhook(**w) for w in data]

    async def create_webhook(
        self, request: WebhookCreateRequest
    ) -> tuple[Webhook, str]:
        """
        Create a webhook.

        Note: This is a two-step process. Asana will send a handshake request
        to the target URL, which must respond with the X-Hook-Secret header.

        Returns:
            Tuple of (Webhook, X-Hook-Secret)
        """
        logger.info(
            f'Creating webhook for resource={request.resource}, target={request.target}'
        )

        payload: dict[str, Any] = {
            'resource': request.resource,
            'target': request.target,
        }
        if request.filters:
            payload['filters'] = [
                f.model_dump(exclude_none=True) for f in request.filters
            ]

        logger.debug(f'Webhook create payload: {payload}')
        response = await self.client.post(
            '/webhooks',
            json={'data': payload},
        )

        if response.status_code >= 400:
            error_body = response.text
            logger.error(
                f'Asana webhook creation failed: status={response.status_code}, '
                f'response={error_body}'
            )
            response.raise_for_status()

        result = response.json()
        webhook = Webhook(**result['data'])
        secret = result.get('X-Hook-Secret', '')
        logger.info(f'Webhook created successfully: gid={webhook.gid}')
        return webhook, secret

    async def delete_webhook(self, webhook_gid: str) -> None:
        """Delete a webhook."""
        logger.info(f'Deleting webhook {webhook_gid}')
        response = await self.client.delete(f'/webhooks/{webhook_gid}')
        response.raise_for_status()

    async def get_user(self, user_gid: str) -> dict[str, Any]:
        """Get a user by GID."""
        response = await self.client.get(f'/users/{user_gid}')
        response.raise_for_status()
        return response.json()['data']

    async def get_me(self) -> dict[str, Any]:
        """Get the current authenticated user."""
        response = await self.client.get('/users/me')
        response.raise_for_status()
        return response.json()['data']

    async def get_projects(
        self,
        workspace_gid: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get projects in a workspace."""
        workspace = workspace_gid or self.workspace_gid
        if not workspace:
            raise ValueError('workspace_gid is required')

        response = await self.client.get(
            '/projects',
            params={
                'workspace': workspace,
                'opt_fields': 'gid,name,archived',
            },
        )
        response.raise_for_status()
        data = response.json()['data']
        # Filter out archived projects
        return [p for p in data if not p.get('archived', False)]

    async def get_workspaces(self) -> list[dict[str, Any]]:
        """Get workspaces for the authenticated user."""
        response = await self.client.get(
            '/workspaces',
            params={'opt_fields': 'gid,name'},
        )
        response.raise_for_status()
        return response.json()['data']

    async def get_tasks_for_user(
        self,
        user_gid: str,
        workspace_gid: str | None = None,
        completed: bool = False,
    ) -> list[AsanaTask]:
        """Get tasks assigned to a user."""
        workspace = workspace_gid or self.workspace_gid
        if not workspace:
            raise ValueError('workspace_gid is required')

        response = await self.client.get(
            '/tasks',
            params={
                'assignee': user_gid,
                'workspace': workspace,
                'completed_since': 'now' if not completed else None,
            },
        )
        response.raise_for_status()
        data = response.json()['data']
        return [AsanaTask(**t) for t in data]
