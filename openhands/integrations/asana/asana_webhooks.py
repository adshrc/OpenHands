"""Webhook handlers for Asana events in OpenHands."""

import hashlib
import hmac
import os
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, Response

from openhands.core.logger import openhands_logger as logger
from openhands.integrations.asana.asana_models import (
    WebhookEvent,
    WebhookPayload,
)
from openhands.storage import get_file_store
from openhands.storage.settings.file_settings_store import FileSettingsStore

router = APIRouter(prefix='/api/webhooks')

# Store webhook secrets in memory (populated from handshake or settings)
webhook_secrets: dict[str, str] = {}

# Track processed events to avoid duplicates
# Key format: "{resource_type}-{resource_gid}-{created_at}" -> True
# This ensures we never process the exact same event twice
_processed_events: set[str] = set()
_MAX_PROCESSED_EVENTS = 1000  # Keep memory bounded


async def get_webhook_secret_from_settings() -> str | None:
    """Load the webhook secret from settings store."""
    try:
        file_store = get_file_store(
            file_store_type='local',
            file_store_path=os.path.expanduser('~/.openhands'),
        )
        settings_store = FileSettingsStore(file_store)
        settings = await settings_store.load()
        if settings and settings.asana_webhook_secret:
            return settings.asana_webhook_secret
    except Exception as e:
        logger.debug(f'Could not load webhook secret from settings: {e}')
    return None


async def get_agent_user_gid_from_settings() -> str | None:
    """Load the agent user GID from settings store."""
    try:
        file_store = get_file_store(
            file_store_type='local',
            file_store_path=os.path.expanduser('~/.openhands'),
        )
        settings_store = FileSettingsStore(file_store)
        settings = await settings_store.load()
        if settings and settings.asana_agent_user_gid:
            return settings.asana_agent_user_gid
    except Exception as e:
        logger.debug(f'Could not load agent user GID from settings: {e}')
    return None


def verify_webhook_signature(body: bytes, signature: str, secret: str) -> bool:
    """
    Verify the webhook signature using HMAC-SHA256.

    Args:
        body: Raw request body
        signature: X-Hook-Signature header value
        secret: The stored X-Hook-Secret from handshake

    Returns:
        True if signature is valid
    """
    computed = hmac.new(
        secret.encode('utf-8'),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(computed, signature)


@router.post('/asana', response_model=None)
async def asana_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hook_secret: str | None = Header(None, alias='X-Hook-Secret'),
    x_hook_signature: str | None = Header(None, alias='X-Hook-Signature'),
) -> Response | dict[str, Any]:
    """
    Handle Asana webhook events.

    This endpoint handles:
    1. Initial handshake (X-Hook-Secret present)
    2. Regular webhook events (X-Hook-Signature present)
    3. Heartbeat events (empty events array)

    IMPORTANT: We return 200 immediately and process events in background
    to avoid Asana retrying due to slow responses.
    """
    body = await request.body()

    # Log all headers for debugging
    headers_dict = dict(request.headers)
    logger.info(f'Asana webhook received - Headers: {headers_dict}')

    # Log raw body (truncate if too large)
    body_str = body.decode('utf-8', errors='replace')
    if len(body_str) > 2000:
        logger.info(f'Asana webhook body (truncated): {body_str[:2000]}...')
    else:
        logger.info(f'Asana webhook body: {body_str}')

    # Handle initial handshake
    if x_hook_secret:
        logger.info('Received webhook handshake request')
        # Store the secret for future verification
        # In production, persist this to a database or settings store
        webhook_secrets['default'] = x_hook_secret
        return Response(
            status_code=200,
            headers={'X-Hook-Secret': x_hook_secret},
        )

    # Verify signature for regular events
    if x_hook_signature:
        stored_secret = webhook_secrets.get('default', '')

        # If not in memory, try to load from settings
        if not stored_secret:
            stored_secret = await get_webhook_secret_from_settings() or ''
            if stored_secret:
                # Cache it for future requests
                webhook_secrets['default'] = stored_secret
                logger.info('Loaded webhook secret from settings store')

        if not stored_secret:
            logger.warning('No webhook secret stored, cannot verify signature')
            raise HTTPException(status_code=401, detail='No webhook secret configured')

        if not verify_webhook_signature(body, x_hook_signature, stored_secret):
            logger.warning('Invalid webhook signature')
            raise HTTPException(status_code=401, detail='Invalid signature')

    # Parse the webhook payload
    try:
        payload_data = await request.json()
        payload = WebhookPayload(**payload_data)
    except Exception as e:
        logger.error(f'Failed to parse webhook payload: {e}')
        raise HTTPException(status_code=400, detail='Invalid payload')

    # Handle heartbeat (empty events)
    if not payload.events:
        logger.debug('Received heartbeat')
        return {'status': 'ok', 'message': 'heartbeat received'}

    # Schedule events for background processing and return immediately
    # This prevents Asana from retrying due to slow response
    for event in payload.events:
        background_tasks.add_task(process_webhook_event_safe, event)

    logger.info(f'Webhook events queued for processing, count={len(payload.events)}')
    return {'status': 'ok', 'queued': len(payload.events)}


async def process_webhook_event_safe(event: WebhookEvent) -> None:
    """Wrapper to safely process webhook events in background."""
    try:
        await process_webhook_event(event)
    except Exception as e:
        logger.error(
            f'Failed to process webhook event in background: '
            f'action={event.action}, resource_gid={event.resource.gid}, error={e}'
        )


async def process_webhook_event(event: WebhookEvent) -> None:
    """
    Process an individual webhook event.

    We're interested in:
    - Task assigned to the agent user (assignee change)
    - Story added with @mention of agent user (comment follow-up)
    """
    # Log full event details for debugging deduplication
    logger.info(
        f'Processing webhook event: '
        f'action={event.action}, '
        f'resource_type={event.resource.resource_type}, '
        f'resource_gid={event.resource.gid}, '
        f'user_gid={getattr(event.user, "gid", None) if event.user else None}, '
        f'created_at={event.created_at}, '
        f'change_field={getattr(event.change, "field", None) if event.change else None}, '
        f'full_event={event.model_dump()}'
    )

    # Handle task events (assignment)
    if event.resource.resource_type == 'task':
        await process_task_event(event)
    # Handle story events (comments with @mentions)
    elif event.resource.resource_type == 'story':
        await process_story_event(event)
    else:
        logger.debug(
            f'Ignoring event type: resource_type={event.resource.resource_type}'
        )


async def process_task_event(event: WebhookEvent) -> None:
    """Process a task webhook event (assignment)."""
    task_gid = event.resource.gid
    logger.info(f'Processing task event: task_gid={task_gid}, action={event.action}')

    # Only process task events
    if event.resource.resource_type != 'task':
        logger.debug(
            f'Ignoring non-task event: resource_type={event.resource.resource_type}'
        )
        return

    # Only process "changed" events (we filter for assignee field in webhook subscription)
    if event.action != 'changed':
        logger.debug(
            f'Ignoring non-changed event: action={event.action}, '
            f'resource_gid={event.resource.gid}'
        )
        return

    # Check for duplicate processing using created_at timestamp
    dedup_key = f'task-{task_gid}-{event.created_at}'
    if dedup_key in _processed_events:
        logger.info(
            f'DEDUP: Skipping duplicate task event: task_gid={task_gid}, '
            f'created_at={event.created_at}, '
            f'action={event.action}, '
            f'change_field={getattr(event.change, "field", None) if event.change else None}'
        )
        return

    # Mark as processed
    _processed_events.add(dedup_key)

    # Clean up old entries if we exceed max (keep oldest entries removed)
    if len(_processed_events) > _MAX_PROCESSED_EVENTS:
        # Remove ~10% of entries (oldest ones will naturally be less likely to repeat)
        to_remove = len(_processed_events) - int(_MAX_PROCESSED_EVENTS * 0.9)
        for _ in range(to_remove):
            _processed_events.pop()

    # Process the task assignment
    logger.info(f'Processing task assignment: task_gid={task_gid}')
    try:
        from openhands.integrations.asana.asana_service import process_task_assignment
        conversation_id = await process_task_assignment(task_gid)
        if conversation_id:
            logger.info(f'Task {task_gid} handled, conversation_id={conversation_id}')
        else:
            logger.info(f'Task {task_gid} skipped (not assigned to agent or error)')
    except Exception as e:
        logger.error(f'Error processing task assignment {task_gid}: {e}', exc_info=True)


async def process_story_event(event: WebhookEvent) -> None:
    """
    Process a story webhook event (comment with @mention).

    Only processes comments where the agent user is @mentioned.
    """
    story_gid = event.resource.gid

    # Only process "added" events (new comments)
    if event.action != 'added':
        logger.debug(
            f'Ignoring non-added story event: action={event.action}, '
            f'resource_gid={story_gid}'
        )
        return

    # Check for duplicate processing using created_at timestamp
    dedup_key = f'story-{story_gid}-{event.created_at}'
    if dedup_key in _processed_events:
        logger.info(
            f'DEDUP: Skipping duplicate story event: story_gid={story_gid}, '
            f'created_at={event.created_at}'
        )
        return

    _processed_events.add(dedup_key)

    # Get parent task GID from event
    parent_gid = None
    if hasattr(event, 'parent') and event.parent:
        parent_gid = event.parent.gid

    # If no parent in event, we need to fetch the story to get it
    if not parent_gid:
        logger.debug(f'No parent GID in event, will fetch from story')

    # Process the story mention
    logger.info(f'Processing story mention: story_gid={story_gid}')
    try:
        from openhands.integrations.asana.asana_service import process_story_mention
        conversation_id = await process_story_mention(story_gid, parent_gid)
        if conversation_id:
            logger.info(f'Story {story_gid} handled, conversation_id={conversation_id}')
        else:
            logger.info(f'Story {story_gid} skipped (agent not mentioned or error)')
    except Exception as e:
        logger.error(f'Error processing story mention {story_gid}: {e}', exc_info=True)


@router.get('/asana/status')
async def webhook_status() -> dict[str, Any]:
    """Get webhook status information."""
    return {
        'configured_secrets': len(webhook_secrets),
        'processed_events_count': len(_processed_events),
    }
