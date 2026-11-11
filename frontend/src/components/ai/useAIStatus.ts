import type { AIStatus } from "../../lib/ai";
import { useApi } from "../../lib/useApi";

export function useAIStatus() {
  return useApi<AIStatus>("/ai/status");
}
