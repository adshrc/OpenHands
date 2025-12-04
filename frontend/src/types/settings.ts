export const ProviderOptions = {
  github: "github",
  gitlab: "gitlab",
  bitbucket: "bitbucket",
  azure_devops: "azure_devops",
  enterprise_sso: "enterprise_sso",
} as const;

export type Provider = keyof typeof ProviderOptions;

export type ProviderToken = {
  token: string;
  host: string | null;
};

export type MCPSSEServer = {
  url: string;
  api_key?: string;
};

export type MCPStdioServer = {
  name: string;
  command: string;
  args?: string[];
  env?: Record<string, string>;
};

export type MCPSHTTPServer = {
  url: string;
  api_key?: string;
  timeout?: number;
};

export type MCPConfig = {
  sse_servers: (string | MCPSSEServer)[];
  stdio_servers: MCPStdioServer[];
  shttp_servers: (string | MCPSHTTPServer)[];
};

export type Settings = {
  LLM_MODEL: string;
  LLM_BASE_URL: string;
  AGENT: string;
  LANGUAGE: string;
  LLM_API_KEY_SET: boolean;
  SEARCH_API_KEY_SET: boolean;
  CONFIRMATION_MODE: boolean;
  SECURITY_ANALYZER: string | null;
  REMOTE_RUNTIME_RESOURCE_FACTOR: number | null;
  PROVIDER_TOKENS_SET: Partial<Record<Provider, string | null>>;
  ENABLE_DEFAULT_CONDENSER: boolean;
  // Maximum number of events before the condenser runs
  CONDENSER_MAX_SIZE: number | null;
  ENABLE_SOUND_NOTIFICATIONS: boolean;
  ENABLE_PROACTIVE_CONVERSATION_STARTERS: boolean;
  ENABLE_SOLVABILITY_ANALYSIS: boolean;
  USER_CONSENTS_TO_ANALYTICS: boolean | null;
  SEARCH_API_KEY?: string;
  IS_NEW_USER?: boolean;
  MCP_CONFIG?: MCPConfig;
  MAX_BUDGET_PER_TASK: number | null;
  EMAIL?: string;
  EMAIL_VERIFIED?: boolean;
  GIT_USER_NAME?: string;
  GIT_USER_EMAIL?: string;
  // Asana integration settings (stored in settings, not as provider tokens)
  ASANA_ACCESS_TOKEN_SET?: boolean;
  ASANA_WEBHOOK_SECRET_SET?: boolean;
  ASANA_AGENT_USER_GID?: string | null;
  ASANA_WORKSPACE_GID?: string | null;
  ASANA_PROJECT_GID?: string | null;
};

export type PostSettings = Settings & {
  user_consents_to_analytics: boolean | null;
  llm_api_key?: string | null;
  search_api_key?: string;
  mcp_config?: MCPConfig;
  // Asana settings
  asana_access_token?: string | null;
  asana_webhook_secret?: string | null;
  asana_agent_user_gid?: string | null;
  asana_workspace_gid?: string | null;
  asana_project_gid?: string | null;
};
