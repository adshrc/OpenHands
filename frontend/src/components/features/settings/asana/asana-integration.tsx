import React from "react";
import { useTranslation } from "react-i18next";
import { SettingsInput } from "#/components/features/settings/settings-input";
import { KeyStatusIcon } from "#/components/features/settings/key-status-icon";
import { useSettings } from "#/hooks/query/use-settings";
import {
  useAsanaWebhookStatus,
  useCreateAsanaWebhook,
} from "#/hooks/query/use-asana-webhook";
import { I18nKey } from "#/i18n/declaration";

interface AsanaIntegrationProps {
  onAsanaTokenChange: (value: string) => void;
  onAsanaAgentUserGidChange: (value: string) => void;
  onAsanaWorkspaceGidChange: (value: string) => void;
  onAsanaProjectGidChange: (value: string) => void;
}

export function AsanaIntegration({
  onAsanaTokenChange,
  onAsanaAgentUserGidChange,
  onAsanaWorkspaceGidChange,
  onAsanaProjectGidChange,
}: AsanaIntegrationProps) {
  const { t } = useTranslation();
  const { data: settings } = useSettings();
  const { data: webhookStatus, isLoading: isLoadingStatus } =
    useAsanaWebhookStatus();
  const createWebhook = useCreateAsanaWebhook();

  // Check if Asana is configured from settings
  const isAsanaTokenSet = settings?.ASANA_ACCESS_TOKEN_SET ?? false;
  const hasWorkspaceGid = !!settings?.ASANA_WORKSPACE_GID;
  const hasProjectGid = !!settings?.ASANA_PROJECT_GID;

  // Determine if Asana is configured enough to check/create webhook
  const hasRequiredConfig = isAsanaTokenSet && hasWorkspaceGid && hasProjectGid;

  const handleCreateWebhook = async (
    e: React.MouseEvent<HTMLButtonElement>,
  ) => {
    e.preventDefault(); // Prevent form submission
    createWebhook.mutate();
  };

  const getWebhookStatusDisplay = () => {
    if (isLoadingStatus) {
      return (
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-neutral-500 animate-pulse" />
          <span className="text-sm text-neutral-400">
            {t(I18nKey.SETTINGS$ASANA_CHECKING_STATUS)}
          </span>
        </div>
      );
    }

    if (!hasRequiredConfig) {
      return (
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-yellow-500" />
          <span className="text-sm text-yellow-400">
            {t(I18nKey.SETTINGS$ASANA_CONFIGURE_FIRST)}
          </span>
        </div>
      );
    }

    if (webhookStatus?.error_message) {
      return (
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-red-500" />
            <span className="text-sm text-red-400">
              {t(I18nKey.SETTINGS$ASANA_ERROR_CHECKING_STATUS)}
            </span>
          </div>
          <span className="text-xs text-neutral-500 ml-5">
            {webhookStatus.error_message}
          </span>
        </div>
      );
    }

    if (webhookStatus?.is_registered) {
      return (
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <div
              className={`w-3 h-3 rounded-full ${webhookStatus.is_active ? "bg-green-500" : "bg-yellow-500"}`}
            />
            <span
              className={`text-sm ${webhookStatus.is_active ? "text-green-400" : "text-yellow-400"}`}
            >
              {webhookStatus.is_active
                ? t(I18nKey.SETTINGS$ASANA_WEBHOOK_ACTIVE)
                : t(I18nKey.SETTINGS$ASANA_WEBHOOK_INACTIVE)}
            </span>
          </div>
          {webhookStatus.resource_name && (
            <span className="text-xs text-neutral-500 ml-5">
              {t(I18nKey.SETTINGS$ASANA_MONITORING, {
                resourceName: webhookStatus.resource_name,
              })}
            </span>
          )}
          {webhookStatus.last_success_at && (
            <span className="text-xs text-neutral-500 ml-5">
              {t(I18nKey.SETTINGS$ASANA_LAST_SUCCESS, {
                date: new Date(webhookStatus.last_success_at).toLocaleString(),
              })}
            </span>
          )}
        </div>
      );
    }

    return (
      <div className="flex items-center gap-2">
        <div className="w-3 h-3 rounded-full bg-red-500" />
        <span className="text-sm text-red-400">
          {t(I18nKey.SETTINGS$ASANA_WEBHOOK_NOT_REGISTERED)}
        </span>
      </div>
    );
  };

  const getButtonText = () => {
    if (createWebhook.isPending) {
      return t(I18nKey.SETTINGS$ASANA_CREATING);
    }
    if (webhookStatus?.is_registered) {
      return t(I18nKey.SETTINGS$ASANA_RECREATE_WEBHOOK);
    }
    return t(I18nKey.SETTINGS$ASANA_CREATE_WEBHOOK);
  };

  return (
    <div className="flex flex-col gap-6">
      <SettingsInput
        name="asana-access-token-input"
        label={t(I18nKey.SETTINGS$ASANA_ACCESS_TOKEN)}
        type="password"
        placeholder={isAsanaTokenSet ? "<hidden>" : ""}
        onChange={(value) => onAsanaTokenChange(value)}
        className="w-full max-w-[680px]"
        startContent={
          isAsanaTokenSet && (
            <KeyStatusIcon
              testId="asana-set-token-indicator"
              isSet={isAsanaTokenSet}
            />
          )
        }
      />
      <SettingsInput
        name="asana-agent-user-gid-input"
        label={t(I18nKey.SETTINGS$ASANA_AGENT_USER_GID)}
        type="text"
        defaultValue={settings?.ASANA_AGENT_USER_GID ?? ""}
        placeholder="e.g., 1234567890"
        onChange={(value) => onAsanaAgentUserGidChange(value)}
        className="w-full max-w-[680px]"
      />
      <SettingsInput
        name="asana-workspace-gid-input"
        label={t(I18nKey.SETTINGS$ASANA_WORKSPACE_GID)}
        type="text"
        defaultValue={settings?.ASANA_WORKSPACE_GID ?? ""}
        placeholder="e.g., 1234567890"
        onChange={(value) => onAsanaWorkspaceGidChange(value)}
        className="w-full max-w-[680px]"
      />
      <SettingsInput
        name="asana-project-gid-input"
        label={t(I18nKey.SETTINGS$ASANA_PROJECT_GID)}
        type="text"
        defaultValue={settings?.ASANA_PROJECT_GID ?? ""}
        placeholder="e.g., 1234567890"
        onChange={(value) => onAsanaProjectGidChange(value)}
        className="w-full max-w-[680px]"
      />

      {/* Webhook Status Section */}
      <div className="flex flex-col gap-3">
        <span className="text-sm font-medium text-neutral-200">
          {t(I18nKey.SETTINGS$ASANA_WEBHOOK_STATUS)}
        </span>
        <div className="flex items-start gap-4">
          {getWebhookStatusDisplay()}
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleCreateWebhook}
            disabled={
              !hasRequiredConfig || createWebhook.isPending || isLoadingStatus
            }
            className="w-fit p-2 text-sm rounded-sm disabled:opacity-30 disabled:cursor-not-allowed hover:opacity-80 cursor-pointer bg-primary text-[#0D0F11]"
          >
            {getButtonText()}
          </button>
          {createWebhook.isError && (
            <span className="text-sm text-red-400">
              {t(I18nKey.SETTINGS$ASANA_WEBHOOK_FAILED, {
                error:
                  (createWebhook.error as Error)?.message ||
                  t(I18nKey.ERROR$GENERIC),
              })}
            </span>
          )}
          {createWebhook.isSuccess && (
            <span className="text-sm text-green-400">
              {t(I18nKey.SETTINGS$ASANA_WEBHOOK_SUCCESS)}
            </span>
          )}
        </div>
        <p className="text-xs text-neutral-500">
          {t(I18nKey.SETTINGS$ASANA_WEBHOOK_DESCRIPTION)}
        </p>
      </div>
    </div>
  );
}
