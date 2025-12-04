"""Asana integration service for creating conversations from tasks and comments."""

import json
import os
import re
import time
from dataclasses import dataclass
from types import MappingProxyType
from uuid import uuid4

from markdownify import markdownify as md
from pydantic import SecretStr

from openhands.core.logger import openhands_logger as logger
from openhands.events.action.message import MessageAction
from openhands.events.stream import EventStreamSubscriber
from openhands.integrations.asana.asana_client import AsanaClient
from openhands.integrations.asana.asana_models import AsanaTask, Story
from openhands.integrations.asana.asana_reporter import AsanaConversationListener
from openhands.integrations.provider import PROVIDER_TOKEN_TYPE, ProviderToken
from openhands.integrations.service_types import ProviderType
from openhands.server.services.conversation_service import create_new_conversation
from openhands.server.shared import config, conversation_manager
from openhands.storage import get_file_store
from openhands.storage.data_models.conversation_metadata import ConversationTrigger
from openhands.storage.data_models.settings import Settings
from openhands.storage.secrets.file_secrets_store import FileSecretsStore
from openhands.storage.settings.file_settings_store import FileSettingsStore


# Path for storing Asana task to conversation mappings
ASANA_MAPPING_FILE = 'asana_task_mapping.json'


# Keep track of active listeners to prevent garbage collection
_active_listeners: dict[str, AsanaConversationListener] = {}


# Base URL for conversation links
def get_base_url() -> str:
    """Get the base URL for OpenHands."""
    return os.environ.get('OPENHANDS_BASE_URL', 'http://localhost:3000')


def get_conversation_url(conversation_id: str) -> str:
    """Get the full URL for a conversation."""
    base_url = get_base_url()
    return f'{base_url}/conversations/{conversation_id}'


def asana_html_to_markdown(html_text: str) -> str:
    """
    Convert Asana rich text HTML to Markdown using markdownify.

    Also removes Asana @mention profile links to avoid confusion.

    Args:
        html_text: The Asana HTML text

    Returns:
        Markdown formatted text
    """
    if not html_text:
        return ''

    # First, remove Asana @mention profile links before conversion
    # These appear as <a href="https://app.asana.com/0/profile/USER_GID">@Name</a>
    text = re.sub(
        r'<a[^>]*href=["\']https?://app\.asana\.com/\d+/profile/\d+["\'][^>]*>[^<]*</a>\s*',
        '',
        html_text,
        flags=re.IGNORECASE
    )

    # Use markdownify to convert HTML to Markdown
    # strip=['body'] removes the body wrapper, heading_style='ATX' uses # for headers
    markdown = md(
        text,
        heading_style='ATX',
        bullets='-',
        strip=['body'],
    )

    # Clean up extra whitespace
    markdown = re.sub(r'\n{3,}', '\n\n', markdown)
    markdown = markdown.strip()

    return markdown


def clean_asana_comment(comment_text: str, agent_user_gid: str | None = None) -> str:
    """
    Clean up an Asana comment for sending to the agent.

    Removes:
    - All Asana profile/mention links (to avoid confusion)
    - Leading/trailing whitespace

    Args:
        comment_text: The raw comment text from Asana
        agent_user_gid: The agent's Asana user GID (not used currently, kept for compatibility)

    Returns:
        Cleaned comment text
    """
    if not comment_text:
        return comment_text

    text = comment_text

    # Remove all Asana profile links (format: https://app.asana.com/0/profile/USER_GID)
    text = re.sub(
        r'https?://app\.asana\.com/\d+/profile/\d+\s*',
        '',
        text,
        flags=re.IGNORECASE
    )

    # Remove any other Asana links that might be @mentions
    # (keeping task/project links which might be intentional references)

    # Clean up multiple consecutive whitespace/newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    return text


async def get_task_conversation_mapping() -> dict[str, str]:
    """Load the Asana task GID to conversation ID mapping."""
    try:
        file_store = get_file_store(
            file_store_type='local',
            file_store_path=os.path.expanduser('~/.openhands'),
        )
        content = file_store.read(ASANA_MAPPING_FILE)
        return json.loads(content)
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning(f'Failed to load Asana task mapping: {e}')
        return {}


async def save_task_conversation_mapping(mapping: dict[str, str]) -> None:
    """Save the Asana task GID to conversation ID mapping."""
    try:
        file_store = get_file_store(
            file_store_type='local',
            file_store_path=os.path.expanduser('~/.openhands'),
        )
        file_store.write(ASANA_MAPPING_FILE, json.dumps(mapping, indent=2))
    except Exception as e:
        logger.warning(f'Failed to save Asana task mapping: {e}')


async def get_conversation_for_task(task_gid: str) -> str | None:
    """Get the existing conversation ID for an Asana task, if any."""
    mapping = await get_task_conversation_mapping()
    conversation_id = mapping.get(task_gid)

    if conversation_id:
        # Verify the conversation still exists
        agent_session = conversation_manager.get_agent_session(conversation_id)
        if agent_session:
            return conversation_id
        else:
            # Conversation no longer exists, remove from mapping
            logger.info(f'Conversation {conversation_id} no longer exists for task {task_gid}')
            del mapping[task_gid]
            await save_task_conversation_mapping(mapping)

    return None


async def set_conversation_for_task(task_gid: str, conversation_id: str) -> None:
    """Store the conversation ID for an Asana task."""
    mapping = await get_task_conversation_mapping()
    mapping[task_gid] = conversation_id
    await save_task_conversation_mapping(mapping)
    logger.info(f'Mapped task {task_gid} to conversation {conversation_id}')


async def remove_conversation_mapping(conversation_id: str) -> bool:
    """Remove a conversation from the Asana task mapping.

    This should be called when a conversation is deleted.

    Args:
        conversation_id: The conversation ID to remove

    Returns:
        True if a mapping was removed, False if no mapping existed
    """
    global _active_listeners

    mapping = await get_task_conversation_mapping()

    # Find and remove the task that maps to this conversation
    task_gid_to_remove = None
    for task_gid, conv_id in mapping.items():
        if conv_id == conversation_id:
            task_gid_to_remove = task_gid
            break

    if task_gid_to_remove:
        del mapping[task_gid_to_remove]
        await save_task_conversation_mapping(mapping)
        logger.info(f'Removed mapping for conversation {conversation_id} (task {task_gid_to_remove})')

    # Also clean up the listener if it exists
    if conversation_id in _active_listeners:
        del _active_listeners[conversation_id]
        logger.info(f'Cleaned up Asana listener for conversation {conversation_id}')

    return task_gid_to_remove is not None


@dataclass
class AsanaSettings:
    """Asana configuration from settings."""
    access_token: str
    workspace_gid: str | None
    project_gid: str | None
    agent_user_gid: str | None


async def load_asana_settings() -> AsanaSettings | None:
    """Load Asana settings from the settings store."""
    try:
        file_store = get_file_store(
            file_store_type='local',
            file_store_path=os.path.expanduser('~/.openhands'),
        )
        settings_store = FileSettingsStore(file_store)
        settings = await settings_store.load()

        if not settings or not settings.asana_access_token:
            logger.warning('Asana access token not configured')
            return None

        return AsanaSettings(
            access_token=settings.asana_access_token,
            workspace_gid=settings.asana_workspace_gid,
            project_gid=settings.asana_project_gid,
            agent_user_gid=settings.asana_agent_user_gid,
        )
    except Exception as e:
        logger.error(f'Failed to load Asana settings: {e}')
        return None


async def process_task_assignment(task_gid: str) -> str | None:
    """
    Process a task assignment event.

    1. Fetch the task details from Asana
    2. Check if assigned to the agent user
    3. Create a new OpenHands conversation
    4. Post a comment back to Asana with the conversation link

    Returns:
        The conversation ID if created, None otherwise.
    """
    asana_settings = await load_asana_settings()
    if not asana_settings:
        logger.error('Cannot process task: Asana settings not configured')
        return None

    async with AsanaClient(
        access_token=asana_settings.access_token,
        workspace_gid=asana_settings.workspace_gid,
    ) as client:
        # Fetch task details
        try:
            task = await client.get_task(task_gid)
            logger.info(f'Fetched task: {task.name} (gid={task.gid})')
        except Exception as e:
            logger.error(f'Failed to fetch task {task_gid}: {e}')
            return None

        # Check if task is assigned to the agent user
        if asana_settings.agent_user_gid:
            assignee_gid = task.assignee.gid if task.assignee else None
            if assignee_gid != asana_settings.agent_user_gid:
                logger.info(
                    f'Task {task_gid} not assigned to agent user '
                    f'(assignee={assignee_gid}, agent={asana_settings.agent_user_gid})'
                )
                return None

        # IMMEDIATELY like the task to acknowledge we received and will process it
        # This gives users fast feedback before the slow conversation creation
        try:
            await client.like_task(task_gid)
            logger.info(f'Liked task {task_gid} as acknowledgment')
        except Exception as e:
            logger.warning(f'Failed to like task {task_gid}: {e}')

        # Build the initial message for OpenHands
        initial_message = build_task_message(task)

        # Check if there's an existing conversation for this task
        existing_conversation_id = await get_conversation_for_task(task_gid)

        if existing_conversation_id:
            # Task was re-assigned but conversation already exists - do nothing
            logger.info(
                f'Task {task_gid} already has conversation {existing_conversation_id}, skipping'
            )
            return existing_conversation_id

        # Create conversation with Asana reporting enabled
        try:
            conversation_id = await create_asana_conversation(
                initial_message=initial_message,
                task_name=task.name,
                task_gid=task_gid,
                asana_access_token=asana_settings.access_token,
                asana_workspace_gid=asana_settings.workspace_gid,
                agent_user_gid=asana_settings.agent_user_gid,
            )
            logger.info(f'Created conversation {conversation_id} for task {task_gid}')
        except Exception as e:
            logger.error(f'Failed to create conversation for task {task_gid}: {e}')
            # Post error comment to Asana
            try:
                await client.add_comment(
                    task_gid,
                    text=f'❌ Failed to start OpenHands: {e}',
                )
            except Exception:
                pass
            return None

        # Store the task-to-conversation mapping
        await set_conversation_for_task(task_gid, conversation_id)

        # Post pinned comment with conversation link
        conversation_url = get_conversation_url(conversation_id)
        try:
            await client.add_comment(
                task_gid,
                text=f'🧑🏽‍💻 Follow progress here:\n{conversation_url}',
                is_pinned=True,
            )
            logger.info(f'Posted pinned conversation link to task {task_gid}')
        except Exception as e:
            logger.warning(f'Failed to post pinned comment to task {task_gid}: {e}')

        return conversation_id


async def send_message_to_conversation(
    conversation_id: str,
    message: str,
    task_gid: str | None = None,
    asana_access_token: str | None = None,
    asana_workspace_gid: str | None = None,
    agent_user_gid: str | None = None,
) -> bool:
    """
    Send a message to an existing conversation.

    Args:
        conversation_id: The conversation ID
        message: The message to send
        task_gid: The Asana task GID (required to re-create listener if needed)
        asana_access_token: Asana access token (required to re-create listener if needed)
        asana_workspace_gid: Optional Asana workspace GID
        agent_user_gid: Optional agent user GID to sanitize from output

    Returns:
        True if message was sent successfully, False otherwise.
    """
    try:
        agent_session = conversation_manager.get_agent_session(conversation_id)
        if not agent_session:
            logger.warning(f'Could not get agent session for conversation {conversation_id}')
            return False

        # Check if listener exists, reset it or re-create it
        if conversation_id in _active_listeners:
            # Reset the existing listener's _reported flag
            listener = _active_listeners[conversation_id]
            listener._reported = False
            listener._start_time = time.time()  # Reset the timer for accurate metrics
            logger.info(f'Reset listener for conversation {conversation_id} to allow re-reporting')
        elif task_gid and asana_access_token:
            # Listener doesn't exist (e.g., server was restarted), re-create it
            logger.info(f'No listener found for conversation {conversation_id}, re-creating it with task_gid={task_gid}')
            try:
                await subscribe_to_conversation_events(
                    conversation_id=conversation_id,
                    task_gid=task_gid,
                    asana_access_token=asana_access_token,
                    asana_workspace_gid=asana_workspace_gid,
                    agent_user_gid=agent_user_gid,
                )
                logger.info(f'Successfully re-created listener for conversation {conversation_id}')
            except Exception as e:
                logger.error(f'Failed to re-create listener for conversation {conversation_id}: {e}', exc_info=True)
        else:
            logger.warning(f'No listener for conversation {conversation_id} and no credentials to re-create it (task_gid={task_gid}, has_token={bool(asana_access_token)})')

        # Create a message action and add it to the event stream
        from openhands.events.event import EventSource
        message_action = MessageAction(content=message)
        agent_session.event_stream.add_event(message_action, EventSource.USER)

        logger.info(f'Sent message to conversation {conversation_id}')
        return True
    except Exception as e:
        logger.error(f'Failed to send message to conversation {conversation_id}: {e}')
        return False


async def process_story_mention(story_gid: str, parent_gid: str | None = None) -> str | None:
    """
    Process a story (comment) where the agent is @mentioned.

    1. Fetch the story details from Asana
    2. Check if the agent user is @mentioned
    3. Check if an existing conversation exists for this task
    4. If yes, send the message to the existing conversation
    5. If no, create a new OpenHands conversation
    6. Post a reply comment with the conversation link

    Args:
        story_gid: The story/comment GID
        parent_gid: The parent task GID (optional, will be fetched from story if not provided)

    Returns:
        The conversation ID if created or reused, None otherwise.
    """
    asana_settings = await load_asana_settings()
    if not asana_settings:
        logger.error('Cannot process story: Asana settings not configured')
        return None

    if not asana_settings.agent_user_gid:
        logger.warning('Agent user GID not configured, cannot check for @mentions')
        return None

    async with AsanaClient(
        access_token=asana_settings.access_token,
        workspace_gid=asana_settings.workspace_gid,
    ) as client:
        # Fetch story details
        try:
            story = await client.get_story(story_gid)
            logger.info(f'Fetched story: type={story.resource_subtype}, gid={story.gid}')
        except Exception as e:
            logger.error(f'Failed to fetch story {story_gid}: {e}')
            return None

        # Only process comment stories
        if story.resource_subtype != 'comment_added':
            logger.debug(f'Ignoring non-comment story: subtype={story.resource_subtype}')
            return None

        # Check if agent is @mentioned in the comment
        # Asana @mentions appear as <a data-asana-gid="USER_GID">@Name</a> in html_text
        agent_mentioned = False
        if story.html_text and asana_settings.agent_user_gid in story.html_text:
            agent_mentioned = True

        if not agent_mentioned:
            logger.debug(f'Agent not mentioned in story {story_gid}')
            return None

        # Get the comment text - prefer html_text and convert to markdown
        if story.html_text:
            comment_text = asana_html_to_markdown(story.html_text)
        else:
            comment_text = story.text or ''

        if not comment_text.strip():
            logger.debug(f'Empty comment in story {story_gid}')
            return None

        # Get parent task GID from story if not provided
        task_gid = parent_gid
        if not task_gid and story.target:
            task_gid = story.target.gid

        if not task_gid:
            logger.warning(f'Could not determine parent task for story {story_gid}')
            return None

        # IMMEDIATELY like the story to acknowledge we received and will process it
        # This gives users fast feedback before the slow conversation operations
        try:
            await client.like_story(story_gid)
            logger.info(f'Liked story {story_gid} as acknowledgment')
        except Exception as e:
            logger.warning(f'Failed to like story {story_gid}: {e}')

        # Clean the comment text (remove agent @mentions, etc.)
        cleaned_comment = clean_asana_comment(comment_text, asana_settings.agent_user_gid)

        # Check if there's an existing conversation for this task
        existing_conversation_id = await get_conversation_for_task(task_gid)

        if existing_conversation_id:
            # Send message to existing conversation (just the cleaned comment, no prefix)
            logger.info(f'Found existing conversation {existing_conversation_id} for task {task_gid}')

            success = await send_message_to_conversation(
                conversation_id=existing_conversation_id,
                message=cleaned_comment,
                task_gid=task_gid,
                asana_access_token=asana_settings.access_token,
                asana_workspace_gid=asana_settings.workspace_gid,
                agent_user_gid=asana_settings.agent_user_gid,
            )

            if success:
                logger.info(f'Message sent to conversation {existing_conversation_id}, response will be posted when ready')
                return existing_conversation_id
            else:
                # Conversation exists in mapping but couldn't send message
                # Fall through to create a new conversation
                logger.warning(f'Could not send to existing conversation, will create new one')

        # NEW conversation from a mention - fetch task details and previous comments for context
        # When someone @mentions the agent in a comment, they're usually asking a question
        # about the task, so we need to provide full task context including discussion history
        try:
            task = await client.get_task(task_gid)
            logger.info(f'Fetched task for mention context: {task.name} (gid={task.gid})')

            # Fetch previous comments on the task for discussion context
            # Filter to only include actual comments (not system activity)
            all_stories = await client.get_task_stories(task_gid)
            previous_comments = [
                s for s in all_stories
                if s.resource_subtype == 'comment_added' and s.gid != story_gid
            ]
            logger.info(f'Found {len(previous_comments)} previous comments on task {task_gid}')

            # Build message with task context + previous comments + the question
            initial_message = build_task_message_with_question(
                task, cleaned_comment, previous_comments
            )
            task_name = task.name
        except Exception as e:
            logger.warning(f'Failed to fetch task {task_gid} for context: {e}')
            # Fall back to just the comment if task fetch fails
            initial_message = cleaned_comment
            task_name = f'Comment follow-up (story {story_gid})'

        # Create new conversation with task context + question
        try:
            conversation_id = await create_asana_conversation(
                initial_message=initial_message,
                task_name=task_name,
                task_gid=task_gid,
                asana_access_token=asana_settings.access_token,
                asana_workspace_gid=asana_settings.workspace_gid,
                agent_user_gid=asana_settings.agent_user_gid,
            )
            logger.info(f'Created conversation {conversation_id} for story {story_gid}')
        except Exception as e:
            logger.error(f'Failed to create conversation for story {story_gid}: {e}')
            return None

        # Store the task-to-conversation mapping
        await set_conversation_for_task(task_gid, conversation_id)

        return conversation_id


def build_task_message(task: AsanaTask) -> str:
    """Build the initial message for OpenHands from an Asana task."""
    parts = []

    # Task title
    parts.append(f'# Asana Task: {task.name}')
    parts.append('')

    # Task description - prefer html_notes and convert to markdown
    if task.html_notes:
        description = asana_html_to_markdown(task.html_notes)
        if description:
            parts.append('## Description')
            parts.append(description)
            parts.append('')
    elif task.notes:
        parts.append('## Description')
        parts.append(task.notes)
        parts.append('')

    # Task metadata
    parts.append('## Task Details')
    parts.append(f'- **Task ID**: {task.gid}')
    if task.permalink_url:
        parts.append(f'- **Link**: {task.permalink_url}')
    if task.due_on:
        parts.append(f'- **Due Date**: {task.due_on}')
    if task.projects:
        project_names = [p.name for p in task.projects if p.name]
        if project_names:
            parts.append(f'- **Projects**: {", ".join(project_names)}')

    parts.append('')
    parts.append('---')
    parts.append('')
    parts.append('Please analyze this task and work on completing it.')

    return '\n'.join(parts)


def build_task_message_with_question(
    task: AsanaTask, question: str, previous_comments: list[Story] | None = None
) -> str:
    """
    Build a message for OpenHands when someone @mentions the agent with a question.

    This includes the task description, previous comments for discussion context,
    and the user's question/comment.

    Args:
        task: The Asana task object
        question: The cleaned comment text (the user's question)
        previous_comments: List of previous Story objects (comments) on the task

    Returns:
        A formatted message with description, previous comments, and the question
    """
    parts = []

    # Task description - prefer html_notes and convert to markdown
    if task.html_notes:
        description = asana_html_to_markdown(task.html_notes)
        if description:
            parts.append('## Description')
            parts.append(description)
            parts.append('')
    elif task.notes:
        parts.append('## Description')
        parts.append(task.notes)
        parts.append('')

    # Add previous comments if any
    if previous_comments:
        parts.append('## Previous Comments')
        parts.append('')
        for comment in previous_comments:
            # Get author name and profile link
            author = comment.created_by.name if comment.created_by else 'Unknown'
            author_gid = comment.created_by.gid if comment.created_by else None
            profile_link = f'https://app.asana.com/0/{author_gid}' if author_gid else ''

            # Get comment text - prefer html_text and convert to markdown
            if comment.html_text:
                comment_text = asana_html_to_markdown(comment.html_text)
            else:
                comment_text = comment.text or ''

            # Format timestamp if available
            timestamp = ''
            if comment.created_at:
                timestamp = f' ({comment.created_at.strftime("%Y-%m-%d %H:%M")})'

            # Format: **Author** (timestamp) (profile_link):
            if profile_link:
                parts.append(f'**{author}**{timestamp} ({profile_link}):')
            else:
                parts.append(f'**{author}**{timestamp}:')
            parts.append(comment_text)
            parts.append('')

    parts.append('---')
    parts.append('')

    # Add the user's question/comment
    parts.append('## Question')
    parts.append('')
    parts.append(question)

    return '\n'.join(parts)


async def load_provider_tokens() -> PROVIDER_TOKEN_TYPE | None:
    """Load provider tokens (GitHub, GitLab, etc.) from the secrets store."""
    try:
        file_store = get_file_store(
            file_store_type='local',
            file_store_path=os.path.expanduser('~/.openhands'),
        )
        secrets_store = FileSecretsStore(file_store)
        secrets = await secrets_store.load()

        if secrets and secrets.provider_tokens:
            logger.info(f'Loaded provider tokens: {list(secrets.provider_tokens.keys())}')
            return secrets.provider_tokens

        logger.debug('No provider tokens found in secrets store')
        return None
    except Exception as e:
        logger.error(f'Failed to load provider tokens: {e}')
        return None


async def create_asana_conversation(
    initial_message: str,
    task_name: str | None = None,
    task_gid: str | None = None,
    asana_access_token: str | None = None,
    asana_workspace_gid: str | None = None,
    agent_user_gid: str | None = None,
) -> str:
    """
    Create a new OpenHands conversation for an Asana task or comment.

    Args:
        initial_message: The initial message to send to the agent
        task_name: Optional task name for context
        task_gid: Optional task GID to subscribe to events and report back
        asana_access_token: Optional Asana access token for reporting
        asana_workspace_gid: Optional Asana workspace GID for reporting
        agent_user_gid: Optional agent user GID to sanitize from output

    Returns:
        The conversation ID
    """
    # For now, we create conversations without a specific user
    # In a production setup, you'd map Asana users to OpenHands users
    user_id = None

    # Load provider tokens so the agent has access to GitHub, etc.
    provider_tokens = await load_provider_tokens()

    agent_loop_info = await create_new_conversation(
        user_id=user_id,
        git_provider_tokens=provider_tokens,
        custom_secrets=None,
        selected_repository=None,
        selected_branch=None,
        initial_user_msg=initial_message,
        image_urls=None,
        replay_json=None,
        conversation_trigger=ConversationTrigger.ASANA,
    )

    conversation_id = agent_loop_info.conversation_id

    # Subscribe to conversation events to report back to Asana
    if task_gid and asana_access_token:
        try:
            await subscribe_to_conversation_events(
                conversation_id=conversation_id,
                task_gid=task_gid,
                asana_access_token=asana_access_token,
                asana_workspace_gid=asana_workspace_gid,
                agent_user_gid=agent_user_gid,
            )
        except Exception as e:
            logger.warning(f'Failed to subscribe to conversation events: {e}')

    return conversation_id


async def subscribe_to_conversation_events(
    conversation_id: str,
    task_gid: str,
    asana_access_token: str,
    asana_workspace_gid: str | None = None,
    agent_user_gid: str | None = None,
) -> None:
    """
    Subscribe to conversation events to report results back to Asana.

    Args:
        conversation_id: The conversation ID
        task_gid: The Asana task GID to post comments to
        asana_access_token: Asana access token
        asana_workspace_gid: Optional Asana workspace GID
        agent_user_gid: Optional agent user GID to sanitize from output
    """
    global _active_listeners

    # Get the agent session for this conversation
    agent_session = conversation_manager.get_agent_session(conversation_id)
    if not agent_session:
        logger.warning(f'Could not get agent session for conversation {conversation_id}')
        return

    if not agent_session.event_stream:
        logger.warning(f'No event stream for conversation {conversation_id}')
        return

    # Create the listener
    conversation_url = get_conversation_url(conversation_id)
    listener = AsanaConversationListener(
        task_gid=task_gid,
        conversation_id=conversation_id,
        conversation_url=conversation_url,
        asana_access_token=asana_access_token,
        asana_workspace_gid=asana_workspace_gid,
        agent_user_gid=agent_user_gid,
    )

    # Store the listener to prevent garbage collection
    _active_listeners[conversation_id] = listener
    logger.info(f'Stored listener for conversation {conversation_id}, total active: {len(_active_listeners)}')

    # Subscribe to the event stream
    callback_id = f'asana_reporter_{conversation_id}'
    try:
        agent_session.event_stream.subscribe(
            EventStreamSubscriber.SERVER,
            listener.create_callback(),
            callback_id,
        )
        logger.info(f'Subscribed to conversation {conversation_id} for Asana reporting to task {task_gid}')
    except ValueError:
        # Already subscribed
        logger.debug(f'Already subscribed to conversation {conversation_id}')

    # Check if the conversation has already reached a terminal state
    # (this handles the race condition where agent finishes before we subscribe)
    from openhands.core.schema.agent import AgentState
    from openhands.events.observation.agent import AgentStateChangedObservation
    from openhands.integrations.asana.asana_reporter import TERMINAL_STATES
    import asyncio as async_module

    # Small delay to let any in-flight events settle
    await async_module.sleep(0.5)

    try:
        # Search for AgentStateChangedObservation events in reverse order
        events = list(agent_session.event_stream.search_events(reverse=True, limit=50))
        logger.info(f'Checking {len(events)} recent events for terminal state in conversation {conversation_id}')
        for event in events:
            event_type = type(event).__name__
            if isinstance(event, AgentStateChangedObservation):
                logger.info(f'Found AgentStateChangedObservation: agent_state={event.agent_state}')
                try:
                    agent_state = AgentState(event.agent_state)
                    if agent_state in TERMINAL_STATES:
                        logger.info(
                            f'Conversation {conversation_id} already in terminal state {agent_state}, '
                            f'triggering immediate report'
                        )
                        # Don't block - call async report directly since we're in async context
                        # Mark as reported to prevent duplicate
                        listener._reported = True
                        try:
                            await listener._report_to_asana(agent_state)
                            logger.info(f'Immediate report completed for conversation {conversation_id}')
                        except Exception as report_error:
                            logger.error(f'Failed immediate report: {report_error}', exc_info=True)
                        break
                except ValueError as ve:
                    logger.warning(f'Invalid agent state value: {event.agent_state}, error: {ve}')
            else:
                logger.debug(f'Event type: {event_type}')
    except Exception as e:
        logger.warning(f'Error checking for existing terminal state: {e}', exc_info=True)
