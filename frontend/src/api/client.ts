import axios from 'axios';
import type {
  PreviewResponse,
  BuildResponse,
  ExploreResponse,
  StatusResponse,
  NeighborResponse,
  AskResponse,
  GraphSchema,
  ChatHistoryResponse,
  ChatLoggerStatusResponse,
} from '../types';

const configuredBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();
const apiBaseUrl = configuredBaseUrl && configuredBaseUrl.length > 0
  ? configuredBaseUrl.replace(/\/$/, '')
  : '/api/v1';

const api = axios.create({
  baseURL: apiBaseUrl,
  headers: { 'Content-Type': 'application/json' },
});

// Graph endpoints
export async function previewSchema(dataDir?: string): Promise<PreviewResponse> {
  const { data } = await api.post<PreviewResponse>('/graph/preview', {
    data_dir: dataDir || null,
  });
  return data;
}

export async function buildGraph(
  graphSchema: GraphSchema,
  clearExisting: boolean = false,
): Promise<BuildResponse> {
  const { data } = await api.post<BuildResponse>('/graph/build', {
    graph_schema: graphSchema,
    clear_existing: clearExisting,
  });
  return data;
}

export async function clearGraph(): Promise<{ message: string }> {
  const { data } = await api.delete<{ message: string }>('/graph/clear');
  return data;
}

export async function exploreGraph(limit: number = 200): Promise<ExploreResponse> {
  const { data } = await api.get<ExploreResponse>('/graph/explore', {
    params: { limit },
  });
  return data;
}

export async function getGraphStatus(): Promise<StatusResponse> {
  const { data } = await api.get<StatusResponse>('/graph/status');
  return data;
}

export async function getNeighbors(nodeId: string, limit: number = 50): Promise<NeighborResponse> {
  const { data } = await api.get<NeighborResponse>(`/graph/neighbors/${encodeURIComponent(nodeId)}`, {
    params: { limit },
  });
  return data;
}

// Query endpoints
export async function askQuestion(
  question: string,
  schemaJson?: GraphSchema,
  sessionId?: string,
): Promise<AskResponse> {
  const { data } = await api.post<AskResponse>('/query/ask', {
    question,
    schema_json: schemaJson || null,
    session_id: sessionId || null,
  });
  return data;
}

export async function getChatLoggerStatus(): Promise<ChatLoggerStatusResponse> {
  const { data } = await api.get<ChatLoggerStatusResponse>('/query/chat/status');
  return data;
}

export async function getChatHistory(sessionId: string, limit: number = 200): Promise<ChatHistoryResponse> {
  const { data } = await api.get<ChatHistoryResponse>('/query/chat/history', {
    params: { session_id: sessionId, limit },
  });
  return data;
}

export async function clearChatHistory(sessionId: string): Promise<{ session_id: string; deleted_count: number }> {
  const { data } = await api.delete<{ session_id: string; deleted_count: number }>('/query/chat/history', {
    params: { session_id: sessionId },
  });
  return data;
}
