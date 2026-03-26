import { useMemo } from 'react';
import type { GraphNode, GraphEdge } from '../types';

const LABEL_COLORS: Record<string, string> = {
  Customer: '#6366f1',
  SalesOrder: '#10b981',
  Delivery: '#8b5cf6',
  Invoice: '#14b8a6',
  JournalEntry: '#3b82f6',
  Payment: '#84cc16',
  Product: '#f59e0b',
  Plant: '#6366f1',
};

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
  queryUsed: string;
  selectedNodeId?: string | null;
  selectedEdgeKey?: string | null;
  onNodeSelect: (nodeId: string) => void;
  onEdgeSelect: (edge: GraphEdge) => void;
  onClose: () => void;
}

function edgeKey(edge: GraphEdge): string {
  return `${edge.source}|${edge.target}|${edge.type}`;
}

function extractPathLines(queryUsed: string): string[] {
  return queryUsed
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => /^MATCH\b/i.test(l) || /^OPTIONAL MATCH\b/i.test(l));
}

/** Get the primary display value for a node. */
function displayValue(node: GraphNode): string {
  const p = node.properties;
  if (typeof p.entity === 'string' && p.entity) {
    return p.entity;
  }
  return (
    p.businessPartnerName ||
    p.plantName ||
    p.productGroup ||
    p.salesOrder ||
    p.deliveryDocument ||
    p.billingDocument ||
    p.accountingDocument ||
    p.product ||
    p[Object.keys(p)[0]] ||
    node.id
  );
}

type BFSLevel = {
  level: number;
  nodes: GraphNode[];
};

function buildBFSLevels(nodes: GraphNode[], edges: GraphEdge[]): BFSLevel[] {
  if (nodes.length === 0) return [];

  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const outgoing = new Map<string, string[]>();
  const indegree = new Map<string, number>();

  for (const n of nodes) {
    indegree.set(n.id, 0);
  }

  for (const e of edges) {
    if (!nodeById.has(e.source) || !nodeById.has(e.target)) continue;
    const list = outgoing.get(e.source) || [];
    list.push(e.target);
    outgoing.set(e.source, list);
    indegree.set(e.target, (indegree.get(e.target) || 0) + 1);
  }

  const roots = nodes
    .filter((n) => (indegree.get(n.id) || 0) === 0)
    .map((n) => n.id);
  const queue = roots.length > 0 ? [...roots] : [nodes[0].id];
  const levelById = new Map<string, number>();

  for (const root of queue) {
    levelById.set(root, 0);
  }

  while (queue.length > 0) {
    const current = queue.shift() as string;
    const currentLevel = levelById.get(current) || 0;
    for (const next of outgoing.get(current) || []) {
      if (levelById.has(next)) continue;
      levelById.set(next, currentLevel + 1);
      queue.push(next);
    }
  }

  // Disconnected leftovers
  let tailLevel = Math.max(...Array.from(levelById.values()), 0) + 1;
  for (const n of nodes) {
    if (!levelById.has(n.id)) {
      levelById.set(n.id, tailLevel);
      tailLevel += 1;
    }
  }

  const grouped = new Map<number, GraphNode[]>();
  for (const n of nodes) {
    const lvl = levelById.get(n.id) || 0;
    const list = grouped.get(lvl) || [];
    list.push(n);
    grouped.set(lvl, list);
  }

  return Array.from(grouped.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([level, levelNodes]) => ({ level, nodes: levelNodes }));
}

export default function QueryPathPanel({
  nodes,
  edges,
  queryUsed,
  selectedNodeId,
  selectedEdgeKey,
  onNodeSelect,
  onEdgeSelect,
  onClose,
}: Props) {
  const pathLines = useMemo(() => extractPathLines(queryUsed), [queryUsed]);
  const bfsLevels = useMemo(() => buildBFSLevels(nodes, edges), [nodes, edges]);

  return (
    <div className="bg-slate-800 border-r border-slate-700 w-72 flex-shrink-0 flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-200">Query Path</h3>
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-slate-200 text-lg leading-none"
          title="Close"
        >
          &times;
        </button>
      </div>

      {/* Summary */}
      <div className="px-4 py-2 border-b border-slate-700/50 text-xs text-slate-400 space-y-1">
        <p>
          {nodes.length} node{nodes.length !== 1 ? 's' : ''},{' '}
          {edges.length} edge{edges.length !== 1 ? 's' : ''}
        </p>
      </div>

      {/* Path lines first for debugging focus */}
      <div className="px-3 py-2 border-b border-slate-700/50">
        <p className="text-xs text-slate-500 mb-1">Execution Path</p>
        {pathLines.length > 0 ? (
          <div className="space-y-1">
            {pathLines.map((line, idx) => (
              <div
                key={`${idx}-${line}`}
                className="text-[11px] font-mono text-cyan-300 bg-slate-900/60 rounded px-2 py-1 break-all"
              >
                {line}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-500">No MATCH path detected.</p>
        )}
      </div>

      {/* BFS traversal view */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {bfsLevels.map((level) => (
          <div key={level.level}>
            <div className="flex items-center gap-2 mb-1.5">
              <span className="text-xs font-semibold text-cyan-300 uppercase tracking-wide">
                Level {level.level}
              </span>
              <span className="text-xs text-slate-500">({level.nodes.length})</span>
            </div>
            <div className="space-y-0.5 ml-2">
              {level.nodes.map((node) => (
                <button
                  key={node.id}
                  onClick={() => onNodeSelect(node.id)}
                  className={`w-full text-left text-xs px-2 py-1.5 rounded transition-colors truncate ${
                    selectedNodeId === node.id
                      ? 'bg-indigo-600/30 text-indigo-200 ring-1 ring-indigo-500/50'
                      : 'text-slate-300 hover:bg-slate-700/50 hover:text-slate-100'
                  }`}
                  title={`${node.label}: ${displayValue(node)}`}
                >
                  <span
                    className="inline-block w-2 h-2 rounded-full mr-1.5"
                    style={{ backgroundColor: LABEL_COLORS[node.label] || '#6366f1' }}
                  />
                  <span className="text-slate-400 mr-1">{node.label}:</span>
                  {displayValue(node)}
                </button>
              ))}
            </div>
          </div>
        ))}

        {/* Edge flow */}
        {edges.length > 0 && (
          <div className="pt-2 border-t border-slate-700/50">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
              Relationships
            </span>
            <div className="mt-1.5 space-y-1">
              {edges.map((edge, i) => {
                const srcNode = nodes.find((n) => n.id === edge.source);
                const tgtNode = nodes.find((n) => n.id === edge.target);
                const isSelected = selectedEdgeKey === edgeKey(edge);
                return (
                  <button
                    key={`${i}-${edgeKey(edge)}`}
                    type="button"
                    onClick={() => onEdgeSelect(edge)}
                    className={`w-full text-left text-xs flex items-center gap-1 truncate rounded px-2 py-1 transition-colors ${
                      isSelected
                        ? 'bg-indigo-600/30 text-indigo-200 ring-1 ring-indigo-500/50'
                        : 'text-slate-400 hover:bg-slate-700/50 hover:text-slate-200'
                    }`}
                    title={`${srcNode?.label || edge.source} -[${edge.type}]-> ${tgtNode?.label || edge.target}`}
                  >
                    <span className="text-slate-300">{srcNode?.label || '?'}</span>
                    <span className="text-slate-500">-[</span>
                    <span className="text-indigo-400">{edge.type}</span>
                    <span className="text-slate-500">]-&gt;</span>
                    <span className="text-slate-300">{tgtNode?.label || '?'}</span>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Cypher query */}
      {queryUsed && (
        <div className="px-3 py-2 border-t border-slate-700">
          <p className="text-xs text-slate-500 mb-1">Cypher</p>
          <pre className="text-xs text-slate-400 font-mono bg-slate-900/50 rounded px-2 py-1.5 max-h-24 overflow-auto break-all whitespace-pre-wrap">
            {queryUsed}
          </pre>
        </div>
      )}
    </div>
  );
}
