"""Asana API routes for webhook management."""

import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from openhands.core.logger import openhands_logger as logger
from openhands.integrations.asana.asana_client import AsanaClient
from openhands.integrations.asana.asana_models import WebhookCreateRequest, WebhookFilter
from openhands.server.dependencies import get_dependencies
from openhands.server.user_auth import (
    get_user_settings,
    get_user_settings_store,
)
from openhands.storage.data_models.settings import Settings
from openhands.storage.settings.settings_store import SettingsStore


app = APIRouter(prefix='/api/asana', dependencies=get_dependencies())


def get_base_url() -> str:
    """Get the base URL for webhooks.

    Reads from OPENHANDS_BASE_URL environment variable.
    Falls back to http://localhost:3000 if not set.
    """
    return os.environ.get('OPENHANDS_BASE_URL', 'http://localhost:3000')


class WebhookStatusResponse(BaseModel):
    """Response model for webhook status."""

    is_registered: bool
    webhook_gid: str | None = None
    is_active: bool | None = None
    target_url: str | None = None
    resource_name: str | None = None
    last_success_at: str | None = None
    last_failure_at: str | None = None
    error_message: str | None = None


class WebhookCreateResponse(BaseModel):
    """Response model for webhook creation."""

    success: bool
    webhook_gid: str | None = None
    message: str


def get_asana_config_from_settings(settings: Settings) -> tuple[str | None, str | None, str | None]:
    """Extract Asana configuration from settings.

    Returns:
        Tuple of (access_token, workspace_gid, project_gid)
    """
    if not settings:
        return None, None, None

    return (
        settings.asana_access_token,
        settings.asana_workspace_gid,
        settings.asana_project_gid,
    )


@app.get(
    '/webhook/status',
    response_model=WebhookStatusResponse,
    responses={
        200: {'description': 'Webhook status retrieved'},
        400: {'description': 'Asana not configured'},
        500: {'description': 'Error checking webhook status'},
    },
)
async def get_webhook_status(
    settings: Settings = Depends(get_user_settings),
) -> WebhookStatusResponse:
    """Check if an Asana webhook is registered for this instance."""
    access_token, workspace_gid, _ = get_asana_config_from_settings(settings)

    if not access_token:
        return WebhookStatusResponse(
            is_registered=False,
            error_message='Asana access token not configured',
        )

    if not workspace_gid:
        return WebhookStatusResponse(
            is_registered=False,
            error_message='Asana workspace GID not configured',
        )

    try:
        async with AsanaClient(
            access_token=access_token,
            workspace_gid=workspace_gid,
        ) as client:
            webhooks = await client.get_webhooks()

            # Find webhook that matches our expected target URL
            base_url = get_base_url()
            expected_target = f'{base_url}/api/webhooks/asana'

            for webhook in webhooks:
                if webhook.target == expected_target:
                    return WebhookStatusResponse(
                        is_registered=True,
                        webhook_gid=webhook.gid,
                        is_active=webhook.active,
                        target_url=webhook.target,
                        resource_name=getattr(webhook.resource, 'name', None) if webhook.resource else None,
                        last_success_at=webhook.last_success_at.isoformat() if webhook.last_success_at else None,
                        last_failure_at=webhook.last_failure_at.isoformat() if webhook.last_failure_at else None,
                    )

            # No matching webhook found
            return WebhookStatusResponse(
                is_registered=False,
            )

    except Exception as e:
        logger.error(f'Error checking Asana webhook status: {e}')
        return WebhookStatusResponse(
            is_registered=False,
            error_message=str(e),
        )


@app.post(
    '/webhook/create',
    response_model=WebhookCreateResponse,
    responses={
        200: {'description': 'Webhook created successfully'},
        400: {'description': 'Asana not configured'},
        500: {'description': 'Error creating webhook'},
    },
)
async def create_webhook(
    settings: Settings = Depends(get_user_settings),
    settings_store: SettingsStore = Depends(get_user_settings_store),
) -> WebhookCreateResponse:
    """Create an Asana webhook and store the secret in settings."""
    access_token, workspace_gid, project_gid = get_asana_config_from_settings(settings)

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Asana access token not configured',
        )

    if not workspace_gid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Asana workspace GID not configured',
        )

    if not project_gid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Asana project GID not configured',
        )

    try:
        base_url = get_base_url()
        target_url = f'{base_url}/api/webhooks/asana'

        # Check if the target URL is localhost - webhooks won't work
        if 'localhost' in target_url or '127.0.0.1' in target_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Cannot create webhook for localhost. Asana requires a publicly accessible HTTPS URL. Set OPENHANDS_BASE_URL environment variable to your public URL.',
            )

        async with AsanaClient(
            access_token=access_token,
            workspace_gid=workspace_gid,
        ) as client:
            # First, check if a webhook already exists and delete it
            webhooks = await client.get_webhooks()
            for webhook in webhooks:
                if webhook.target == target_url:
                    logger.info(f'Deleting existing webhook {webhook.gid}')
                    await client.delete_webhook(webhook.gid)

            # Create new webhook with filters
            filters = [
                # Track task assignee changes
                WebhookFilter(
                    resource_type='task',
                    action='changed',
                    fields=['assignee'],
                ),
                # Track new stories (comments) for @mentions
                WebhookFilter(
                    resource_type='story',
                    action='added',
                ),
            ]

            request = WebhookCreateRequest(
                resource=project_gid,
                target=target_url,
                filters=filters,
            )

            webhook, secret = await client.create_webhook(request)

            # Store the webhook secret in settings
            if secret:
                settings.asana_webhook_secret = secret
                await settings_store.store(settings)
                logger.info(f'Webhook created and secret stored: {webhook.gid}')
            else:
                logger.warning('Webhook created but no secret received')

            return WebhookCreateResponse(
                success=True,
                webhook_gid=webhook.gid,
                message='Webhook created successfully',
            )

    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        # Extract detailed error from Asana API response
        error_detail = str(e)
        try:
            error_json = e.response.json()
            if 'errors' in error_json:
                error_messages = [err.get('message', str(err)) for err in error_json['errors']]
                error_detail = '; '.join(error_messages)
        except Exception:
            error_detail = e.response.text or str(e)

        logger.error(f'Asana API error creating webhook: {error_detail}')
        raise HTTPException(
            status_code=e.response.status_code,
            detail=error_detail,
        )
    except Exception as e:
        logger.error(f'Error creating Asana webhook: {e}')
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@app.delete(
    '/webhook',
    responses={
        200: {'description': 'Webhook deleted successfully'},
        400: {'description': 'Asana not configured'},
        404: {'description': 'No webhook found'},
        500: {'description': 'Error deleting webhook'},
    },
)
async def delete_webhook(
    settings: Settings = Depends(get_user_settings),
    settings_store: SettingsStore = Depends(get_user_settings_store),
) -> JSONResponse:
    """Delete the Asana webhook."""
    access_token, workspace_gid, _ = get_asana_config_from_settings(settings)

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Asana access token not configured',
        )

    if not workspace_gid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Asana workspace GID not configured',
        )

    try:
        base_url = get_base_url()
        target_url = f'{base_url}/api/webhooks/asana'

        async with AsanaClient(
            access_token=access_token,
            workspace_gid=workspace_gid,
        ) as client:
            webhooks = await client.get_webhooks()
            deleted = False

            for webhook in webhooks:
                if webhook.target == target_url:
                    await client.delete_webhook(webhook.gid)
                    deleted = True
                    logger.info(f'Deleted webhook {webhook.gid}')

            if deleted:
                # Clear the webhook secret from settings
                settings.asana_webhook_secret = None
                await settings_store.store(settings)

                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={'message': 'Webhook deleted successfully'},
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail='No webhook found to delete',
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f'Error deleting Asana webhook: {e}')
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
