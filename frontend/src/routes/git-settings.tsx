import React from "react";
import { useTranslation } from "react-i18next";
import { useConfig } from "#/hooks/query/use-config";
import { useSettings } from "#/hooks/query/use-settings";
import { BrandButton } from "#/components/features/settings/brand-button";
import { useLogout } from "#/hooks/mutation/use-logout";
import { GitHubTokenInput } from "#/components/features/settings/git-settings/github-token-input";
import { GitLabTokenInput } from "#/components/features/settings/git-settings/gitlab-token-input";
import { BitbucketTokenInput } from "#/components/features/settings/git-settings/bitbucket-token-input";
import { AzureDevOpsTokenInput } from "#/components/features/settings/git-settings/azure-devops-token-input";
import { ConfigureGitHubRepositoriesAnchor } from "#/components/features/settings/git-settings/configure-github-repositories-anchor";
import { InstallSlackAppAnchor } from "#/components/features/settings/git-settings/install-slack-app-anchor";
import { I18nKey } from "#/i18n/declaration";
import {
  displayErrorToast,
  displaySuccessToast,
} from "#/utils/custom-toast-handlers";
import { retrieveAxiosErrorMessage } from "#/utils/retrieve-axios-error-message";
import { GitSettingInputsSkeleton } from "#/components/features/settings/git-settings/github-settings-inputs-skeleton";
import { useAddGitProviders } from "#/hooks/mutation/use-add-git-providers";
import { useSaveSettings } from "#/hooks/mutation/use-save-settings";
import { useUserProviders } from "#/hooks/use-user-providers";
import { ProjectManagementIntegration } from "#/components/features/settings/project-management/project-management-integration";
import { AsanaIntegration } from "#/components/features/settings/asana/asana-integration";

function GitSettingsScreen() {
  const { t } = useTranslation();

  const { mutate: saveGitProviders, isPending: isGitPending } =
    useAddGitProviders();
  const { mutate: saveSettings, isPending: isSettingsPending } =
    useSaveSettings();
  const { mutate: disconnectGitTokens } = useLogout();

  const { data: settings, isLoading } = useSettings();
  const { providers } = useUserProviders();

  const { data: config } = useConfig();

  // Git provider state
  const [githubTokenInputHasValue, setGithubTokenInputHasValue] =
    React.useState(false);
  const [gitlabTokenInputHasValue, setGitlabTokenInputHasValue] =
    React.useState(false);
  const [bitbucketTokenInputHasValue, setBitbucketTokenInputHasValue] =
    React.useState(false);
  const [azureDevOpsTokenInputHasValue, setAzureDevOpsTokenInputHasValue] =
    React.useState(false);

  const [githubHostInputHasValue, setGithubHostInputHasValue] =
    React.useState(false);
  const [gitlabHostInputHasValue, setGitlabHostInputHasValue] =
    React.useState(false);
  const [bitbucketHostInputHasValue, setBitbucketHostInputHasValue] =
    React.useState(false);
  const [azureDevOpsHostInputHasValue, setAzureDevOpsHostInputHasValue] =
    React.useState(false);

  // Asana state
  const [asanaTokenInputHasValue, setAsanaTokenInputHasValue] =
    React.useState(false);
  const [asanaAgentUserGidInputHasValue, setAsanaAgentUserGidInputHasValue] =
    React.useState(false);
  const [asanaWorkspaceGidInputHasValue, setAsanaWorkspaceGidInputHasValue] =
    React.useState(false);
  const [asanaProjectGidInputHasValue, setAsanaProjectGidInputHasValue] =
    React.useState(false);

  const existingGithubHost = settings?.PROVIDER_TOKENS_SET.github;
  const existingGitlabHost = settings?.PROVIDER_TOKENS_SET.gitlab;
  const existingBitbucketHost = settings?.PROVIDER_TOKENS_SET.bitbucket;
  const existingAzureDevOpsHost = settings?.PROVIDER_TOKENS_SET.azure_devops;

  const isSaas = config?.APP_MODE === "saas";
  const isGitHubTokenSet = providers.includes("github");
  const isGitLabTokenSet = providers.includes("gitlab");
  const isBitbucketTokenSet = providers.includes("bitbucket");
  const isAzureDevOpsTokenSet = providers.includes("azure_devops");
  const isPending = isGitPending || isSettingsPending;

  const formAction = async (formData: FormData) => {
    const disconnectButtonClicked =
      formData.get("disconnect-tokens-button") !== null;

    if (disconnectButtonClicked) {
      disconnectGitTokens();
      return;
    }

    const githubToken = formData.get("github-token-input")?.toString() || "";
    const gitlabToken = formData.get("gitlab-token-input")?.toString() || "";
    const bitbucketToken =
      formData.get("bitbucket-token-input")?.toString() || "";
    const azureDevOpsToken =
      formData.get("azure-devops-token-input")?.toString() || "";
    const githubHost = formData.get("github-host-input")?.toString() || "";
    const gitlabHost = formData.get("gitlab-host-input")?.toString() || "";
    const bitbucketHost =
      formData.get("bitbucket-host-input")?.toString() || "";
    const azureDevOpsHost =
      formData.get("azure-devops-host-input")?.toString() || "";

    // Asana fields
    const asanaToken =
      formData.get("asana-access-token-input")?.toString() || "";
    const asanaAgentUserGid =
      formData.get("asana-agent-user-gid-input")?.toString() || "";
    const asanaWorkspaceGid =
      formData.get("asana-workspace-gid-input")?.toString() || "";
    const asanaProjectGid =
      formData.get("asana-project-gid-input")?.toString() || "";

    // Check if any values changed
    const hasGitChanges =
      githubToken ||
      gitlabToken ||
      bitbucketToken ||
      azureDevOpsToken ||
      githubHost ||
      gitlabHost ||
      bitbucketHost ||
      azureDevOpsHost;
    const hasAsanaChanges =
      asanaToken ||
      asanaAgentUserGidInputHasValue ||
      asanaWorkspaceGidInputHasValue ||
      asanaProjectGidInputHasValue;

    if (!hasGitChanges && !hasAsanaChanges) {
      return;
    }

    const onSettled = () => {
      setGithubTokenInputHasValue(false);
      setGitlabTokenInputHasValue(false);
      setBitbucketTokenInputHasValue(false);
      setAzureDevOpsTokenInputHasValue(false);
      setGithubHostInputHasValue(false);
      setGitlabHostInputHasValue(false);
      setBitbucketHostInputHasValue(false);
      setAzureDevOpsHostInputHasValue(false);
      setAsanaTokenInputHasValue(false);
      setAsanaAgentUserGidInputHasValue(false);
      setAsanaWorkspaceGidInputHasValue(false);
      setAsanaProjectGidInputHasValue(false);
    };

    // Handle Asana settings separately via settings API
    if (hasAsanaChanges) {
      saveSettings(
        {
          // Only include fields that were actually modified
          // Send empty string "" to clear, undefined to keep existing
          asana_access_token: asanaToken || undefined,
          asana_agent_user_gid: asanaAgentUserGidInputHasValue
            ? asanaAgentUserGid
            : undefined,
          asana_workspace_gid: asanaWorkspaceGidInputHasValue
            ? asanaWorkspaceGid
            : undefined,
          asana_project_gid: asanaProjectGidInputHasValue
            ? asanaProjectGid
            : undefined,
        },
        {
          onSuccess: () => {
            if (!hasGitChanges) {
              displaySuccessToast(t(I18nKey.SETTINGS$SAVED));
            }
          },
          onError: (error) => {
            const errorMessage = retrieveAxiosErrorMessage(error);
            displayErrorToast(errorMessage || t(I18nKey.ERROR$GENERIC));
          },
          onSettled: hasGitChanges ? undefined : onSettled,
        },
      );
    }

    // Handle git providers via secrets API
    if (hasGitChanges) {
      const providerTokens: Record<string, { token: string; host: string }> = {
        github: { token: githubToken, host: githubHost },
        gitlab: { token: gitlabToken, host: gitlabHost },
        bitbucket: { token: bitbucketToken, host: bitbucketHost },
        azure_devops: { token: azureDevOpsToken, host: azureDevOpsHost },
      };

      saveGitProviders(
        {
          providers: providerTokens,
        },
        {
          onSuccess: () => {
            displaySuccessToast(t(I18nKey.SETTINGS$SAVED));
          },
          onError: (error) => {
            const errorMessage = retrieveAxiosErrorMessage(error);
            displayErrorToast(errorMessage || t(I18nKey.ERROR$GENERIC));
          },
          onSettled,
        },
      );
    }
  };

  const gitFormIsClean =
    !githubTokenInputHasValue &&
    !gitlabTokenInputHasValue &&
    !bitbucketTokenInputHasValue &&
    !azureDevOpsTokenInputHasValue &&
    !githubHostInputHasValue &&
    !gitlabHostInputHasValue &&
    !bitbucketHostInputHasValue &&
    !azureDevOpsHostInputHasValue;

  const asanaFormIsClean =
    !asanaTokenInputHasValue &&
    !asanaAgentUserGidInputHasValue &&
    !asanaWorkspaceGidInputHasValue &&
    !asanaProjectGidInputHasValue;

  const formIsClean = gitFormIsClean && asanaFormIsClean;
  const shouldRenderExternalConfigureButtons = isSaas && config.APP_SLUG;
  const shouldRenderProjectManagementIntegrations =
    config?.FEATURE_FLAGS?.ENABLE_JIRA ||
    config?.FEATURE_FLAGS?.ENABLE_JIRA_DC ||
    config?.FEATURE_FLAGS?.ENABLE_LINEAR;

  return (
    <form
      data-testid="git-settings-screen"
      action={formAction}
      className="flex flex-col h-full justify-between"
    >
      {!isLoading && (
        <div className="flex flex-col">
          {shouldRenderExternalConfigureButtons && !isLoading && (
            <>
              <div className="pb-1 flex flex-col">
                <h3 className="text-xl font-medium text-white">
                  {t(I18nKey.SETTINGS$GITHUB)}
                </h3>
                <ConfigureGitHubRepositoriesAnchor slug={config.APP_SLUG!} />
              </div>
              <div className="w-1/2 border-b border-gray-200" />
            </>
          )}

          {shouldRenderExternalConfigureButtons && !isLoading && (
            <>
              <div className="pb-1 mt-6 flex flex-col">
                <h3 className="text-xl font-medium text-white">
                  {t(I18nKey.SETTINGS$SLACK)}
                </h3>
                <InstallSlackAppAnchor />
              </div>
              <div className="w-1/2 border-b border-gray-200" />
            </>
          )}

          {shouldRenderProjectManagementIntegrations && !isLoading && (
            <div className="mt-6">
              <ProjectManagementIntegration />
            </div>
          )}

          <div className="flex flex-col gap-4">
            {!isSaas && (
              <GitHubTokenInput
                name="github-token-input"
                isGitHubTokenSet={isGitHubTokenSet}
                onChange={(value) => {
                  setGithubTokenInputHasValue(!!value);
                }}
                onGitHubHostChange={(value) => {
                  setGithubHostInputHasValue(!!value);
                }}
                githubHostSet={existingGithubHost}
              />
            )}

            {!isSaas && (
              <GitLabTokenInput
                name="gitlab-token-input"
                isGitLabTokenSet={isGitLabTokenSet}
                onChange={(value) => {
                  setGitlabTokenInputHasValue(!!value);
                }}
                onGitLabHostChange={(value) => {
                  setGitlabHostInputHasValue(!!value);
                }}
                gitlabHostSet={existingGitlabHost}
              />
            )}

            {!isSaas && (
              <BitbucketTokenInput
                name="bitbucket-token-input"
                isBitbucketTokenSet={isBitbucketTokenSet}
                onChange={(value) => {
                  setBitbucketTokenInputHasValue(!!value);
                }}
                onBitbucketHostChange={(value) => {
                  setBitbucketHostInputHasValue(!!value);
                }}
                bitbucketHostSet={existingBitbucketHost}
              />
            )}

            {!isSaas && (
              <AzureDevOpsTokenInput
                name="azure-devops-token-input"
                isAzureDevOpsTokenSet={isAzureDevOpsTokenSet}
                onChange={(value) => {
                  setAzureDevOpsTokenInputHasValue(!!value);
                }}
                onAzureDevOpsHostChange={(value) => {
                  setAzureDevOpsHostInputHasValue(!!value);
                }}
                azureDevOpsHostSet={existingAzureDevOpsHost}
              />
            )}
          </div>

          {/* Asana Integration - available for all modes */}
          {!isLoading && (
            <div className="mt-6">
              <AsanaIntegration
                onAsanaTokenChange={(value: string) =>
                  setAsanaTokenInputHasValue(!!value)
                }
                onAsanaAgentUserGidChange={(value: string) =>
                  setAsanaAgentUserGidInputHasValue(!!value)
                }
                onAsanaWorkspaceGidChange={(value: string) =>
                  setAsanaWorkspaceGidInputHasValue(!!value)
                }
                onAsanaProjectGidChange={(value: string) =>
                  setAsanaProjectGidInputHasValue(!!value)
                }
              />
            </div>
          )}
        </div>
      )}

      {isLoading && <GitSettingInputsSkeleton />}

      <div className="flex gap-6 p-6 justify-end">
        {!shouldRenderExternalConfigureButtons && (
          <>
            <BrandButton
              testId="disconnect-tokens-button"
              name="disconnect-tokens-button"
              type="submit"
              variant="secondary"
              isDisabled={
                !isGitHubTokenSet &&
                !isGitLabTokenSet &&
                !isBitbucketTokenSet &&
                !isAzureDevOpsTokenSet
              }
            >
              {t(I18nKey.GIT$DISCONNECT_TOKENS)}
            </BrandButton>
            <BrandButton
              testId="submit-button"
              type="submit"
              variant="primary"
              isDisabled={isPending || formIsClean}
            >
              {!isPending && t("SETTINGS$SAVE_CHANGES")}
              {isPending && t("SETTINGS$SAVING")}
            </BrandButton>
          </>
        )}
      </div>
    </form>
  );
}

export default GitSettingsScreen;
