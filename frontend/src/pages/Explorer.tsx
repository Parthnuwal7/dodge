import { useCallback, useEffect, useRef, useState } from 'react';
import CytoscapeGraph, { type CytoscapeGraphHandle } from '../components/CytoscapeGraph';
import ChatPanel from '../components/ChatPanel';
import NodeDetailPanel from '../components/NodeDetailPanel';
import QueryPathPanel from '../components/QueryPathPanel';
import { getGraphStatus, exploreGraph, getNeighbors } from '../api/client';
import type { AskResponse, GraphNode, GraphEdge, StatusResponse } from '../types';

type ViewMode = 'full' | 'query';

type QueryPathHint = { sourceLabel: string; targetLabel: string; edgeType: string };
type SelectedQueryEdge = { source: string; target: string; type: string };
const MAX_QUERY_NODES = 120;
const MAX_QUERY_EDGES = 180;

function extractQueryPathHints(cypher: string): { labels: string[]; edgeTypes: string[]; paths: QueryPathHint[] } {
  const varLabels = new Map<string, string>();
  const labelRegex = /\((\w+)\s*:\s*`?(\w+)`?(?:\s*\{[^}]*\})?\)/g;
  const allLabels = new Set<string>();
  let lm: RegExpExecArray | null;
  while ((lm = labelRegex.exec(cypher)) !== null) {
    varLabels.set(lm[1], lm[2]);
    allLabels.add(lm[2]);
  }

  const relRegex = /\((\w+)(?:\s*:\s*`?\w+`?)?(?:\s*\{[^}]*\})?\)\s*(<-|-)\[:`?(\w+)`?\](->|-)\s*\((\w+)(?:\s*:\s*`?\w+`?)?(?:\s*\{[^}]*\})?\)/g;
  const labels: string[] = [];
  const edgeTypes: string[] = [];
  const paths: QueryPathHint[] = [];
  let rm: RegExpExecArray | null;
  while ((rm = relRegex.exec(cypher)) !== null) {
    const [, v1, leftArrow, relType, rightArrow, v2] = rm;
    const sourceVar = leftArrow === '<-' ? v2 : v1;
    const targetVar = rightArrow === '->' ? v2 : v1;
    const sourceLabel = varLabels.get(sourceVar);
    const targetLabel = varLabels.get(targetVar);
    if (sourceLabel) labels.push(sourceLabel);
    if (targetLabel) labels.push(targetLabel);
    edgeTypes.push(relType);
    if (sourceLabel && targetLabel) {
      paths.push({ sourceLabel, targetLabel, edgeType: relType });
    }
  }

  return {
    labels: Array.from(new Set([...labels, ...allLabels])),
    edgeTypes: Array.from(new Set(edgeTypes)),
    paths,
  };
}

function buildEntityPathGraph(hints: { labels: string[]; paths: QueryPathHint[] }): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes: GraphNode[] = hints.labels.map((label) => ({
    id: `entity:${label}`,
    label,
    properties: { entity: label },
  }));

  const seen = new Set<string>();
  const edges: GraphEdge[] = [];
  let idx = 0;
  for (const p of hints.paths) {
    const source = `entity:${p.sourceLabel}`;
    const target = `entity:${p.targetLabel}`;
    const key = `${source}|${target}|${p.edgeType}`;
    if (seen.has(key)) continue;
    seen.add(key);
    edges.push({
      source,
      target,
      type: p.edgeType,
      properties: { order: String(idx++) },
    });
  }

  return { nodes, edges };
}

function buildRelevantQueryGraph(
  result: AskResponse,
  hints: { labels: string[]; paths: QueryPathHint[] },
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodeById = new Map(result.nodes.map((node) => [node.id, node]));
  const dedupedEdges: GraphEdge[] = [];
  const seenEdges = new Set<string>();

  for (const edge of result.edges) {
    if (!edge.source || !edge.target) continue;
    const key = `${edge.source}|${edge.target}|${edge.type}`;
    if (seenEdges.has(key)) continue;
    seenEdges.add(key);
    dedupedEdges.push(edge);
    if (dedupedEdges.length >= MAX_QUERY_EDGES) break;
  }

  const referencedNodeIds = new Set<string>();
  dedupedEdges.forEach((edge) => {
    referencedNodeIds.add(edge.source);
    referencedNodeIds.add(edge.target);
  });

  const referencedNodes: GraphNode[] = [];
  for (const nodeId of referencedNodeIds) {
    const node = nodeById.get(nodeId);
    if (node) referencedNodes.push(node);
  }

  if (referencedNodes.length > 0) {
    const cappedNodes = referencedNodes.slice(0, MAX_QUERY_NODES);
    const allowedNodeIds = new Set(cappedNodes.map((node) => node.id));
    const cappedEdges = dedupedEdges
      .filter((edge) => allowedNodeIds.has(edge.source) && allowedNodeIds.has(edge.target))
      .slice(0, MAX_QUERY_EDGES);
    return { nodes: cappedNodes, edges: cappedEdges };
  }

  if (result.nodes.length > 0) {
    return { nodes: result.nodes.slice(0, MAX_QUERY_NODES), edges: [] };
  }

  return buildEntityPathGraph(hints);
}

export default function Explorer() {
  const [fullNodes, setFullNodes] = useState<GraphNode[]>([]);
  const [fullEdges, setFullEdges] = useState<GraphEdge[]>([]);
  const [queryNodes, setQueryNodes] = useState<GraphNode[]>([]);
  const [queryEdges, setQueryEdges] = useState<GraphEdge[]>([]);
  const [queryCypher, setQueryCypher] = useState('');
  const [queryLabels, setQueryLabels] = useState<string[]>([]);
  const [queryEdgeTypes, setQueryEdgeTypes] = useState<string[]>([]);
  const [selectedQueryEdge, setSelectedQueryEdge] = useState<SelectedQueryEdge | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('full');
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [statusError, setStatusError] = useState('');
  const [graphLoading, setGraphLoading] = useState(true);

  // Node detail & expansion state
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [expandedNodeIds, setExpandedNodeIds] = useState<Set<string>>(new Set());
  const [expandLoading, setExpandLoading] = useState(false);
  const graphRef = useRef<CytoscapeGraphHandle>(null);

  // Track all known nodes for expand click lookups
  const allNodesRef = useRef<Map<string, GraphNode>>(new Map());

  // Load status + full graph on mount
  useEffect(() => {
    getGraphStatus()
      .then((s) => {
        setStatus(s);
        if (s.connected && s.total_nodes > 0) {
          return exploreGraph(300);
        }
        return null;
      })
      .then((result) => {
        if (result) {
          setFullNodes(result.nodes);
          setFullEdges(result.edges);
          result.nodes.forEach((n) => allNodesRef.current.set(n.id, n));
        }
      })
      .catch(() => setStatusError('Could not connect to backend'))
      .finally(() => setGraphLoading(false));
  }, []);

  const handleResult = useCallback((result: AskResponse) => {
    const cypher = result.query_used || '';
    const hints = extractQueryPathHints(cypher);
    const relevantGraph = buildRelevantQueryGraph(result, hints);
    setQueryNodes(relevantGraph.nodes);
    setQueryEdges(relevantGraph.edges);
    setQueryCypher(cypher);
    setQueryLabels(Array.from(new Set([...hints.labels, ...relevantGraph.nodes.map((node) => node.label)])));
    setQueryEdgeTypes(Array.from(new Set([...hints.edgeTypes, ...relevantGraph.edges.map((edge) => edge.type)])));
    setSelectedQueryEdge(null);
    setViewMode('query');
  }, []);

  const handleNodeClick = (nodeId: string, nodeData: GraphNode) => {
    if (!nodeId) {
      setSelectedNode(null);
      return;
    }
    // Use stored node data if available (has full properties)
    const stored = allNodesRef.current.get(nodeId);
    setSelectedNode(stored || nodeData);
  };

  const handleExpand = async () => {
    if (!selectedNode || expandedNodeIds.has(selectedNode.id)) return;
    setExpandLoading(true);
    try {
      const result = await getNeighbors(selectedNode.id);
      // Store new nodes
      result.nodes.forEach((n) => allNodesRef.current.set(n.id, n));

      // Add to graph imperatively
      graphRef.current?.addElements(result.nodes, result.edges);

      // Track as expanded
      setExpandedNodeIds((prev) => new Set(prev).add(selectedNode.id));

      // Also update state arrays for consistency
      setFullNodes((prev) => {
        const existingIds = new Set(prev.map((n) => n.id));
        const newOnes = result.nodes.filter((n) => !existingIds.has(n.id));
        return [...prev, ...newOnes];
      });
      setFullEdges((prev) => [...prev, ...result.edges]);
    } catch {
      // silently handle
    } finally {
      setExpandLoading(false);
    }
  };

  const handlePathNodeSelect = (nodeId: string) => {
    setSelectedQueryEdge(null);
    const node = queryNodes.find((n) => n.id === nodeId);
    if (node) {
      setSelectedNode(node);
    }
  };

  const handlePathEdgeSelect = (edge: GraphEdge) => {
    setSelectedNode(null);
    setSelectedQueryEdge({ source: edge.source, target: edge.target, type: edge.type });
  };

  const hasQueryGraph = queryNodes.length > 0 || queryEdges.length > 0;
  const displayNodes = viewMode === 'query' ? queryNodes : fullNodes;
  const displayEdges = viewMode === 'query' ? queryEdges : fullEdges;
  const hasQueryResults = queryCypher.length > 0 || hasQueryGraph || queryLabels.length > 0;

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Query path panel (left side, shown in query view) */}
      {viewMode === 'query' && hasQueryResults && (
        <QueryPathPanel
          nodes={queryNodes}
          edges={queryEdges}
          queryUsed={queryCypher}
          selectedNodeId={selectedNode?.id}
          selectedEdgeKey={selectedQueryEdge ? `${selectedQueryEdge.source}|${selectedQueryEdge.target}|${selectedQueryEdge.type}` : null}
          onNodeSelect={handlePathNodeSelect}
          onEdgeSelect={handlePathEdgeSelect}
          onClose={() => {
            setSelectedQueryEdge(null);
            setViewMode('full');
          }}
        />
      )}

      {/* Main graph canvas */}
      <div className="flex-1 flex flex-col">
        {/* Status bar */}
        <div className="px-4 py-2 bg-slate-800/50 border-b border-slate-700 flex items-center gap-4 text-xs text-slate-400">
          {statusError ? (
            <span className="text-red-400">{statusError}</span>
          ) : status ? (
            <>
              <span className="flex items-center gap-1.5">
                <span
                  className={`w-2 h-2 rounded-full ${
                    status.connected ? 'bg-green-400' : 'bg-red-400'
                  }`}
                />
                Neo4j {status.connected ? 'connected' : 'disconnected'}
              </span>
              <span>{status.total_nodes.toLocaleString()} nodes</span>
              <span>{status.total_relationships.toLocaleString()} relationships</span>
              <span>{status.node_labels.length} labels</span>
            </>
          ) : (
            <span className="animate-pulse">Connecting...</span>
          )}

          {/* View toggle */}
          <div className="ml-auto flex items-center gap-1 bg-slate-800 rounded-lg p-0.5">
            <button
              onClick={() => setViewMode('full')}
              className={`px-3 py-1 rounded text-xs transition-colors ${
                viewMode === 'full'
                  ? 'bg-slate-600 text-slate-100'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Full Graph
            </button>
            <button
              onClick={() => setViewMode('query')}
              disabled={!hasQueryResults}
              className={`px-3 py-1 rounded text-xs transition-colors ${
                viewMode === 'query'
                  ? 'bg-indigo-600 text-white'
                  : hasQueryResults
                    ? 'text-slate-400 hover:text-slate-200'
                    : 'text-slate-600 cursor-not-allowed'
              }`}
            >
              Query Results
            </button>
          </div>
        </div>

        {/* Graph area */}
        <div className="flex-1 p-4">
          {graphLoading ? (
            <div className="w-full h-full flex items-center justify-center text-slate-500">
              <p className="animate-pulse">Loading graph...</p>
            </div>
          ) : displayNodes.length === 0 ? (
            <div className="w-full h-full flex items-center justify-center text-slate-500">
              <p className="text-center">
                {viewMode === 'full'
                  ? 'No graph data yet. Go to Ingestion to build your graph.'
                  : hasQueryResults
                    ? 'No relevant graph path found for this query.'
                    : 'Ask a question in the chat panel to visualize results.'}
              </p>
            </div>
          ) : (
            <CytoscapeGraph
              ref={graphRef}
              nodes={displayNodes}
              edges={displayEdges}
              onNodeClick={handleNodeClick}
              selectedNodeId={selectedNode?.id}
              layoutMode={viewMode}
              highlightedNodeIds={queryNodes.map((n) => n.id)}
              highlightedNodeLabels={queryLabels}
              highlightedEdgeTypes={queryEdgeTypes}
              focusedNodeIds={selectedQueryEdge ? [selectedQueryEdge.source, selectedQueryEdge.target] : []}
              focusedEdge={selectedQueryEdge}
            />
          )}
        </div>
      </div>

      {/* Node detail panel (shown when a node is selected) */}
      {selectedNode && selectedNode.id && (
        <NodeDetailPanel
          node={selectedNode}
          expanded={expandedNodeIds.has(selectedNode.id)}
          onExpand={handleExpand}
          onClose={() => setSelectedNode(null)}
          loading={expandLoading}
        />
      )}

      {/* Chat sidebar */}
      <div className="w-96 flex-shrink-0">
        <ChatPanel onResult={handleResult} />
      </div>
    </div>
  );
}
