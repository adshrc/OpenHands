"""Asana reporter module for posting conversation results, progress, and errors back to Asana tasks."""

import html
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import mistune

from openhands.core.logger import openhands_logger as logger
from openhands.core.schema.agent import AgentState
from openhands.events.event import Event, EventSource
from openhands.events.observation.agent import AgentStateChangedObservation
from openhands.events.observation.observation import Observation
from openhands.events.action.message import MessageAction
from openhands.integrations.asana.asana_client import AsanaClient


# Terminal states that indicate conversation completion
TERMINAL_STATES = {
    AgentState.FINISHED,
    AgentState.STOPPED,
    AgentState.ERROR,
    AgentState.REJECTED,
    AgentState.AWAITING_USER_INPUT,  # Agent completed and waiting for user response
}


class AsanaHTMLRenderer(mistune.HTMLRenderer):
    """
    Custom mistune renderer that outputs Asana-compatible HTML.

    Asana supports: <strong>, <em>, <u>, <s>, <code>, <pre>, <a>,
    <ul>, <ol>, <li>, <blockquote>, <h1>, <h2>
    Newlines are preserved (rendered with white-space: pre-wrap).
    """

    def codespan(self, text: str) -> str:
        """Inline code -> <code>"""
        return f'<code>{text}</code>'

    def block_code(self, code: str, info: str | None = None) -> str:
        """Code blocks -> <pre>"""
        return f'<pre>{html.escape(code.strip(), quote=False)}</pre>\n'

    def strong(self, text: str) -> str:
        return f'<strong>{text}</strong>'

    def emphasis(self, text: str) -> str:
        return f'<em>{text}</em>'

    def strikethrough(self, text: str) -> str:
        """Asana uses <s> for strikethrough"""
        return f'<s>{text}</s>'

    def link(self, text: str, url: str, title: str | None = None) -> str:
        return f'<a href="{url}">{text}</a>'

    def heading(self, text: str, level: int, **attrs) -> str:
        """Asana only supports h1, h2; use <strong> for others"""
        if level <= 2:
            return f'<h{level}>{text}</h{level}>\n'
        return f'<strong>{text}</strong>\n'

    def paragraph(self, text: str) -> str:
        """No <p> tags in Asana, just use newlines"""
        return f'{text}\n\n'

    def list(self, text: str, ordered: bool, **attrs) -> str:
        tag = 'ol' if ordered else 'ul'
        return f'<{tag}>\n{text}</{tag}>\n'

    def list_item(self, text: str, **attrs) -> str:
        return f'<li>{text.strip()}</li>\n'

    def block_quote(self, text: str) -> str:
        return f'<blockquote>{text.strip()}</blockquote>\n'

    def newline(self) -> str:
        """Preserve newlines"""
        return '\n'

    def softbreak(self) -> str:
        """Soft breaks become newlines"""
        return '\n'

    def linebreak(self) -> str:
        """Hard line breaks become newlines (Asana doesn't use <br>)"""
        return '\n'

    def thematic_break(self) -> str:
        """Horizontal rules -> just a separator line"""
        return '\n---\n'


# Create the markdown parser with our custom Asana renderer
_asana_markdown = mistune.create_markdown(
    renderer=AsanaHTMLRenderer(),
    plugins=['strikethrough'],
)


def sanitize_agent_mentions(text: str, agent_user_gid: str | None) -> str:
    """
    Remove or sanitize any @mentions of the agent user from text.

    This prevents the agent from @mentioning itself and causing infinite loops.

    Args:
        text: The text to sanitize
        agent_user_gid: The agent's Asana user GID to look for

    Returns:
        Sanitized text with agent mentions removed
    """
    if not text or not agent_user_gid:
        return text

    # Remove Asana-style @mention links: <a data-asana-gid="USER_GID">@Name</a>
    text = re.sub(
        rf'<a[^>]*data-asana-gid="{re.escape(agent_user_gid)}"[^>]*>@[^<]*</a>',
        '',
        text,
        flags=re.IGNORECASE
    )

    # Remove any URLs containing the agent user GID (profile links etc)
    text = re.sub(
        rf'https?://[^\s<>"]*{re.escape(agent_user_gid)}[^\s<>"]*',
        '[link removed]',
        text,
        flags=re.IGNORECASE
    )

    # Remove markdown-style links containing the agent user GID
    text = re.sub(
        rf'\[[^\]]*\]\([^)]*{re.escape(agent_user_gid)}[^)]*\)',
        '',
        text,
        flags=re.IGNORECASE
    )

    return text


def markdown_to_asana_html(markdown_text: str, agent_user_gid: str | None = None) -> str:
    """
    Convert markdown text to Asana-compatible HTML using mistune.

    Asana supports HTML in Stories (comments) including:
    - <strong> for bold
    - <em> for italic
    - <u> for underline
    - <s> for strikethrough
    - <code> for inline monospace
    - <pre> for pre-formatted code blocks
    - <a href="..."> for links
    - <ul>, <ol>, <li> for lists
    - <blockquote> for quotes
    - <h1>, <h2> for headers
    - Newlines are preserved (rendered with white-space: pre-wrap)

    Args:
        markdown_text: The markdown text to convert
        agent_user_gid: Optional agent user GID to sanitize from output

    Returns:
        Asana-compatible HTML string for use in html_text field
    """
    if not markdown_text:
        return ''

    # First, sanitize any agent user mentions to prevent self-mention loops
    text = sanitize_agent_mentions(markdown_text, agent_user_gid)

    # Convert markdown to Asana HTML using our custom renderer
    result = _asana_markdown(text)

    # Clean up extra whitespace
    result = re.sub(r'\n{3,}', '\n\n', result)
    result = result.strip()

    return result


def format_metrics(
    duration_seconds: Optional[int] = None,
    cost: Optional[float] = None,
) -> str:
    """
    Format execution metrics as a string.

    Args:
        duration_seconds: Execution duration in seconds
        cost: LLM cost in dollars

    Returns:
        Formatted metrics string like "⏱️ 0m 51s • 💰 $0.0354"
    """
    parts = []

    if duration_seconds is not None:
        minutes = duration_seconds // 60
        seconds = duration_seconds % 60
        parts.append(f'⏱️ {minutes}m {seconds}s')

    if cost is not None:
        parts.append(f'💰 ${cost:.4f}')

    if parts:
        return ' • '.join(parts)
    return ''


def format_agent_result(
    events: list[Event],
    agent_state: AgentState,
    conversation_url: str,
    duration_seconds: Optional[int] = None,
    cost: Optional[float] = None,
    agent_user_gid: Optional[str] = None,
) -> str:
    """
    Format the agent's result for posting to Asana.

    Extracts the most recent assistant message and formats it for Asana.

    Args:
        events: List of events from the conversation
        agent_state: Final state of the agent
        conversation_url: URL to the conversation
        duration_seconds: Optional duration in seconds
        cost: Optional LLM cost in dollars
        agent_user_gid: Optional agent user GID to sanitize from output

    Returns:
        Formatted HTML string for Asana comment
    """
    logger.info(f'format_agent_result: processing {len(events)} events')

    # Log all events for debugging
    for i, event in enumerate(events):
        event_type = type(event).__name__
        event_source = getattr(event, '_source', None)
        has_content = hasattr(event, 'content') and event.content
        logger.debug(f'  Event {i}: type={event_type}, source={event_source}, has_content={has_content}')

    # Find the last assistant message (the agent's final response)
    last_message = None
    for i, event in enumerate(reversed(events)):
        # Look for MessageAction from the agent (assistant messages)
        if isinstance(event, MessageAction):
            event_source = getattr(event, '_source', None)
            # Also check the source property in case _source doesn't exist
            if event_source is None:
                event_source = event.source
            logger.info(f'format_agent_result: found MessageAction at index -{i + 1}, source={event_source}, content_preview={event.content[:100] if event.content else "None"}...')
            # Agent messages have source EventSource.AGENT or 'agent'
            if event_source == EventSource.AGENT or event_source == 'agent':
                last_message = event.content
                logger.info(f'format_agent_result: MATCHED agent message, length={len(last_message) if last_message else 0}')
                break
        # Also look for Observations with content
        elif isinstance(event, Observation) and hasattr(event, 'content'):
            if event.content and not isinstance(event, AgentStateChangedObservation):
                last_message = event.content
                logger.info(f'format_agent_result: found observation with content, length={len(last_message) if last_message else 0}')
                break

    if not last_message:
        logger.warning('format_agent_result: no agent message found in events')

    # Build the result message
    parts = []

    # Agent's response (no status header, just the content)
    if last_message:
        # Convert markdown to Asana HTML and truncate if needed
        # Pass agent_user_gid to sanitize self-mentions and prevent loops
        formatted_message = markdown_to_asana_html(last_message, agent_user_gid=agent_user_gid)
        # Asana has a limit on comment length (~65535 chars)
        if len(formatted_message) > 10000:
            formatted_message = formatted_message[:10000] + '...\n<em>(truncated)</em>'
        parts.append(formatted_message)
        parts.append('\n\n')

    # Add metrics (time and cost)
    metrics = format_metrics(duration_seconds, cost)
    if metrics:
        parts.append(f'<em>{metrics}</em>')

    return ''.join(parts)


async def report_result(
    client: AsanaClient,
    task_gid: str,
    events: list[Event],
    agent_state: AgentState,
    conversation_url: str,
    duration_seconds: Optional[int] = None,
    cost: Optional[float] = None,
    agent_user_gid: Optional[str] = None,
) -> bool:
    """
    Report the final result of a conversation to Asana.

    Args:
        client: Asana client
        task_gid: The task GID to post the comment to
        events: List of events from the conversation
        agent_state: Final state of the agent
        conversation_url: URL to the conversation
        duration_seconds: Optional duration in seconds
        cost: Optional LLM cost in dollars
        agent_user_gid: Optional agent user GID to sanitize from output

    Returns:
        True if comment was posted successfully, False otherwise
    """
    try:
        logger.info(f'report_result: formatting {len(events)} events for task {task_gid}')
        html_content = format_agent_result(
            events,
            agent_state,
            conversation_url,
            duration_seconds=duration_seconds,
            cost=cost,
            agent_user_gid=agent_user_gid,
        )
        logger.info(f'report_result: html_content length={len(html_content)}')

        # Wrap in body tags as required by Asana API
        wrapped_html = f'<body>{html_content}</body>'
        logger.info(f'report_result: posting comment with {len(wrapped_html)} chars to task {task_gid}...')

        await client.add_comment(
            task_gid,
            html_text=wrapped_html,
        )
        logger.info(f'report_result: Successfully posted result to task {task_gid}')
        return True
    except Exception as e:
        logger.error(f'report_result: Failed to post result to task {task_gid}: {e}', exc_info=True)
        return False


async def report_error(
    client: AsanaClient,
    task_gid: str,
    error_message: str,
    conversation_url: str | None = None,
) -> bool:
    """
    Report an error to Asana.

    Args:
        client: Asana client
        task_gid: The task GID to post the comment to
        error_message: The error message
        conversation_url: Optional URL to the conversation

    Returns:
        True if comment was posted successfully, False otherwise
    """
    try:
        parts = [
            '<strong>❌ OpenHands Error</strong>',
            '\n\n',
            f'<code>{html.escape(error_message, quote=False)}</code>',
        ]

        if conversation_url:
            parts.append('\n\n')
            parts.append(f'<a href="{conversation_url}">View conversation →</a>')

        # Wrap in body tags as required by Asana API
        wrapped_html = f'<body>{"".join(parts)}</body>'

        await client.add_comment(
            task_gid,
            html_text=wrapped_html,
        )
        logger.info(f'Posted error to task {task_gid}')
        return True
    except Exception as e:
        logger.error(f'Failed to post error to task {task_gid}: {e}')
        return False


async def report_progress(
    client: AsanaClient,
    task_gid: str,
    message: str,
    conversation_url: str | None = None,
) -> bool:
    """
    Report progress to Asana.

    Args:
        client: Asana client
        task_gid: The task GID to post the comment to
        message: The progress message
        conversation_url: Optional URL to the conversation

    Returns:
        True if comment was posted successfully, False otherwise
    """
    try:
        parts = [
            '<strong>🔄 OpenHands Update</strong>',
            '\n\n',
            markdown_to_asana_html(message),
        ]

        if conversation_url:
            parts.append('\n\n')
            parts.append(f'<a href="{conversation_url}">View conversation →</a>')

        # Wrap in body tags as required by Asana API
        wrapped_html = f'<body>{"".join(parts)}</body>'

        await client.add_comment(
            task_gid,
            html_text=wrapped_html,
        )
        logger.info(f'Posted progress to task {task_gid}')
        return True
    except Exception as e:
        logger.error(f'Failed to post progress to task {task_gid}: {e}')
        return False


@dataclass
class AsanaConversationListener:
    """
    Listener that subscribes to conversation events and reports to Asana.

    This class creates an event callback that listens for agent state changes
    and posts results back to Asana when the conversation completes.
    """
    task_gid: str
    conversation_id: str
    conversation_url: str
    asana_access_token: str
    asana_workspace_gid: str | None
    agent_user_gid: str | None = None
    _reported: bool = False
    _start_time: float = field(default_factory=time.time)

    def create_callback(self) -> Callable[[Event], None]:
        """
        Create a callback function for event stream subscription.

        Returns:
            A callback function that handles events
        """
        def callback(event: Event) -> None:
            # Log every event at info level for debugging
            event_type = type(event).__name__
            logger.info(
                f'Asana callback received event: type={event_type}, '
                f'conversation_id={self.conversation_id}, task_gid={self.task_gid}'
            )

            # Only handle AgentStateChangedObservation events
            if not isinstance(event, AgentStateChangedObservation):
                logger.debug(f'Skipping non-AgentStateChangedObservation event: {event_type}')
                return

            logger.info(
                f'Asana callback received AgentStateChangedObservation: '
                f'agent_state={event.agent_state}, conversation_id={self.conversation_id}'
            )

            # Check if this is a terminal state
            try:
                agent_state = AgentState(event.agent_state)
            except ValueError:
                logger.warning(f'Invalid agent state value: {event.agent_state}')
                return

            if agent_state not in TERMINAL_STATES:
                logger.debug(f'Non-terminal state {agent_state}, skipping')
                return

            # Prevent duplicate reports
            if self._reported:
                logger.debug(f'Already reported for conversation {self.conversation_id}, skipping')
                return
            self._reported = True

            logger.info(
                f'Conversation {self.conversation_id} reached terminal state: {agent_state}, '
                f'will report to Asana task {self.task_gid}'
            )

            # Import here to avoid circular imports
            import asyncio
            from openhands.utils.async_utils import call_async_from_sync

            # Report to Asana with extended timeout (60 seconds)
            ASANA_REPORT_TIMEOUT = 60
            try:
                logger.info(f'Calling _report_to_asana with timeout={ASANA_REPORT_TIMEOUT}s...')
                call_async_from_sync(
                    self._report_to_asana,
                    ASANA_REPORT_TIMEOUT,
                    agent_state,
                )
                logger.info('call_async_from_sync completed successfully')
            except asyncio.TimeoutError:
                logger.error(f'Timeout calling _report_to_asana after {ASANA_REPORT_TIMEOUT}s')
            except Exception as e:
                logger.error(f'Error calling _report_to_asana: {e}', exc_info=True)

        return callback

    async def _report_to_asana(self, agent_state: AgentState) -> None:
        """
        Report the conversation result to Asana.

        Args:
            agent_state: The final agent state
        """
        logger.info(f'_report_to_asana STARTED for conversation {self.conversation_id}, state={agent_state}')
        try:
            # Get events from the conversation
            logger.info('Getting conversation_manager...')
            from openhands.server.shared import conversation_manager

            logger.info(f'Getting agent session for {self.conversation_id}...')
            agent_session = conversation_manager.get_agent_session(self.conversation_id)
            if not agent_session:
                logger.warning(
                    f'Could not get agent session for conversation {self.conversation_id}'
                )
                return
            if not agent_session.event_stream:
                logger.warning(
                    f'Could not get event stream for conversation {self.conversation_id}'
                )
                return

            logger.info(f'Searching events for conversation {self.conversation_id}...')
            events = list(agent_session.event_stream.search_events())
            logger.info(f'Got {len(events)} events from conversation {self.conversation_id}')

            # Calculate duration
            duration_seconds = int(time.time() - self._start_time)

            # Get cost from conversation stats
            cost = None
            try:
                if agent_session.conversation_stats:
                    metrics = agent_session.conversation_stats.get_combined_metrics()
                    cost = metrics.accumulated_cost
                    logger.info(f'Got conversation cost: ${cost:.4f}')
            except Exception as e:
                logger.warning(f'Failed to get conversation cost: {e}')

            # Report to Asana
            logger.info(f'Posting result to Asana task {self.task_gid}...')
            async with AsanaClient(
                access_token=self.asana_access_token,
                workspace_gid=self.asana_workspace_gid,
            ) as client:
                success = await report_result(
                    client=client,
                    task_gid=self.task_gid,
                    events=events,
                    agent_state=agent_state,
                    conversation_url=self.conversation_url,
                    duration_seconds=duration_seconds,
                    cost=cost,
                    agent_user_gid=self.agent_user_gid,
                )
                logger.info(f'Posted result to Asana task {self.task_gid}, success={success}')

            # Note: We don't delete the listener from _active_listeners here
            # because follow-up messages may come in and we want to report those too.
            # The listener's _reported flag will be reset by send_message_to_conversation.
            # Cleanup happens when the conversation is deleted.

        except Exception as e:
            logger.error(f'Error reporting to Asana for conversation {self.conversation_id}: {e}', exc_info=True)
