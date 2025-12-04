import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { openHands } from "#/api/open-hands-axios";

interface WebhookStatus {
  is_registered: boolean;
  webhook_gid: string | null;
  is_active: boolean | null;
  target_url: string | null;
  resource_name: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  error_message: string | null;
}

interface WebhookCreateResponse {
  success: boolean;
  webhook_gid: string | null;
  message: string;
}

export function useAsanaWebhookStatus() {
  return useQuery<WebhookStatus>({
    queryKey: ["asana-webhook-status"],
    queryFn: async () => {
      const response = await openHands.get("/api/asana/webhook/status");
      return response.data;
    },
    staleTime: 30_000, // 30 seconds
    retry: false,
  });
}

export function useCreateAsanaWebhook() {
  const queryClient = useQueryClient();

  return useMutation<WebhookCreateResponse, Error>({
    mutationFn: async () => {
      const response = await openHands.post("/api/asana/webhook/create");
      return response.data;
    },
    onSuccess: () => {
      // Invalidate the webhook status query to refetch
      queryClient.invalidateQueries({ queryKey: ["asana-webhook-status"] });
      // Also invalidate settings since webhook secret was stored
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });
}

export function useDeleteAsanaWebhook() {
  const queryClient = useQueryClient();

  return useMutation<void, Error>({
    mutationFn: async () => {
      await openHands.delete("/api/asana/webhook");
    },
    onSuccess: () => {
      // Invalidate the webhook status query to refetch
      queryClient.invalidateQueries({ queryKey: ["asana-webhook-status"] });
      // Also invalidate settings since webhook secret was cleared
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });
}
