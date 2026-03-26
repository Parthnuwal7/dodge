// Graph Schema types (mirrors backend Pydantic models)
export interface NodeSchema {
  label: string;
  source_entity?: string;
  properties: Record<string, string>;
  id_field: string | string[];
}

export interface EdgeSchema {
  type: string;
  from_node: string;
  to_node: string;
  join_on: [string, string];
}

export interface GraphSchema {
  nodes: NodeSchema[];
  edges: EdgeSchema[];
}

// API response types
export interface PreviewResponse {
  graph_schema: GraphSchema;
  node_count: number;
  edge_count: number;
}

export interface BuildReport {
  nodes_created: Record<string, number>;
  edges_created: Record<string, number>;
  errors: string[];
}

export interface BuildResponse {
  report: BuildReport;
}

export interface ExploreResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface StatusResponse {
  connected: boolean;
  node_labels: string[];
  relationship_types: string[];
  total_nodes: number;
  total_relationships: number;
}

// Query types
export interface GraphNode {
  id: string;
  label: string;
  properties: Record<string, string>;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
  properties: Record<string, string>;
}

export interface NeighborResponse {
  center_node: GraphNode;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface AskResponse {
  answer: string;
  explanation: string;
  query_used: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  data: Record<string, unknown>[];
  metadata: Record<string, unknown>;
}

export interface ChatLoggerStatusResponse {
  enabled: boolean;
  connected: boolean;
  table: string;
  message: string;
}

export interface ChatHistoryItem {
  created_at: string;
  session_id: string | null;
  question: string;
  answer: string;
  explanation: string;
  query_used: string;
  metadata: Record<string, unknown>;
  node_count: number;
  edge_count: number;
  record_count: number;
  status: string;
  error: string | null;
}

export interface ChatHistoryResponse {
  session_id: string;
  items: ChatHistoryItem[];
}
