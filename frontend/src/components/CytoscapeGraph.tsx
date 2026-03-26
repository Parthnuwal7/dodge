import { useEffect, useRef, useCallback, useImperativeHandle, forwardRef } from 'react';
import cytoscape, { type Core } from 'cytoscape';
import type { GraphNode, GraphEdge } from '../types';

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onNodeClick?: (nodeId: string, nodeData: GraphNode) => void;
  selectedNodeId?: string | null;
  /** Use 'query' for path-focused breadthfirst layout, 'full' for cose (default). */
  layoutMode?: 'full' | 'query';
  highlightedNodeIds?: string[];
  highlightedNodeLabels?: string[];
  highlightedEdgeTypes?: string[];
  focusedNodeIds?: string[];
  focusedEdge?: { source: string; target: string; type: string } | null;
}

export interface CytoscapeGraphHandle {
  addElements: (nodes: GraphNode[], edges: GraphEdge[]) => void;
}

const LABEL_COLORS: Record<string, string> = {};
const PALETTE = [
  '#6366f1', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6',
  '#ec4899', '#14b8a6', '#f97316', '#3b82f6', '#84cc16',
];

function colorForLabel(label: string): string {
  if (!LABEL_COLORS[label]) {
    LABEL_COLORS[label] = PALETTE[Object.keys(LABEL_COLORS).length % PALETTE.length];
  }
  return LABEL_COLORS[label];
}

function toNodeElement(n: GraphNode): cytoscape.ElementDefinition {
  return {
    data: {
      id: n.id,
      label: n.label,
      displayName: n.properties.businessPartnerName
        || n.properties.plantName
        || n.properties.productGroup
        || n.properties.salesOrder
        || n.properties.deliveryDocument
        || n.properties.billingDocument
        || n.properties[Object.keys(n.properties)[0]]
        || n.label,
      color: colorForLabel(n.label),
    },
  };
}

function toEdgeElement(e: GraphEdge, index: number): cytoscape.ElementDefinition {
  return {
    data: {
      id: `edge-${e.source}-${e.target}-${e.type}-${index}`,
      source: e.source,
      target: e.target,
      label: e.type,
    },
  };
}

const CytoscapeGraph = forwardRef<CytoscapeGraphHandle, Props>(
  ({
    nodes,
    edges,
    onNodeClick,
    selectedNodeId,
    layoutMode = 'full',
    highlightedNodeIds = [],
    highlightedNodeLabels = [],
    highlightedEdgeTypes = [],
    focusedNodeIds = [],
    focusedEdge = null,
  }, ref) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const cyRef = useRef<Core | null>(null);
    const edgeCountRef = useRef(0);

    // Expose addElements for imperative neighbor expansion
    useImperativeHandle(ref, () => ({
      addElements(newNodes: GraphNode[], newEdges: GraphEdge[]) {
        const cy = cyRef.current;
        if (!cy) return;

        const existingIds = new Set(cy.nodes().map((n) => n.id()));
        const nodesToAdd = newNodes
          .filter((n) => !existingIds.has(n.id))
          .map((n) => toNodeElement(n));

        const edgesToAdd = newEdges
          .filter((e) => {
            // Only add if both endpoints exist (or are being added)
            const allIds = new Set([...existingIds, ...newNodes.map((n) => n.id)]);
            return allIds.has(e.source) && allIds.has(e.target);
          })
          .map((e) => {
            edgeCountRef.current += 1;
            return toEdgeElement(e, edgeCountRef.current);
          });

        if (nodesToAdd.length > 0 || edgesToAdd.length > 0) {
          cy.add([...nodesToAdd, ...edgesToAdd]);
          // Run layout only on new nodes
          const newIds = nodesToAdd.map((n) => n.data.id);
          if (newIds.length > 0) {
            const newCollection = cy.nodes().filter((n) => newIds.includes(n.id()));
            newCollection.layout({
              name: 'concentric',
              animate: true,
              animationDuration: 300,
              fit: false,
              concentric: () => 1,
              levelWidth: () => 2,
              minNodeSpacing: 60,
            } as cytoscape.LayoutOptions).run();
          }
        }
      },
    }));

    // Build graph on initial data
    useEffect(() => {
      if (!containerRef.current) return;

      edgeCountRef.current = 0;
      const elements: cytoscape.ElementDefinition[] = [
        ...nodes.map((n) => toNodeElement(n)),
        ...edges.map((e, i) => {
          edgeCountRef.current = i;
          return toEdgeElement(e, i);
        }),
      ];

      if (cyRef.current) {
        cyRef.current.destroy();
      }

      cyRef.current = cytoscape({
        container: containerRef.current,
        elements,
        style: [
          {
            selector: 'node',
            style: {
              'background-color': 'data(color)',
              label: 'data(displayName)',
              'font-size': '11px',
              color: '#e2e8f0',
              'text-outline-color': '#1e293b',
              'text-outline-width': 2,
              width: 40,
              height: 40,
              'text-max-width': '80px',
              'text-wrap': 'ellipsis',
            },
          },
          {
            selector: 'node.selected',
            style: {
              'border-width': 3,
              'border-color': '#facc15',
              width: 50,
              height: 50,
            },
          },
          {
            selector: 'node.query-highlighted',
            style: {
              'border-width': 4,
              'border-color': '#22d3ee',
            },
          },
          {
            selector: 'node.focused',
            style: {
              'border-width': 5,
              'border-color': '#f59e0b',
              width: 52,
              height: 52,
            },
          },
          {
            selector: 'edge.highlighted',
            style: {
              width: 3,
              'line-color': '#818cf8',
              'target-arrow-color': '#818cf8',
              'z-index': 10,
            },
          },
          {
            selector: 'edge.focused',
            style: {
              width: 5,
              'line-color': '#f59e0b',
              'target-arrow-color': '#f59e0b',
              'z-index': 20,
            },
          },
          {
            selector: 'edge',
            style: {
              width: 2,
              'line-color': '#475569',
              'target-arrow-color': '#475569',
              'target-arrow-shape': 'triangle',
              'curve-style': 'bezier',
              label: 'data(label)',
              'font-size': '9px',
              color: '#94a3b8',
              'text-rotation': 'autorotate',
            },
          },
        ],
        layout: layoutMode === 'query'
          ? {
              name: 'breadthfirst',
              directed: true,
              spacingFactor: 1.5,
              animate: true,
              animationDuration: 400,
            } as cytoscape.LayoutOptions
          : {
              name: 'cose',
              animate: false,
              nodeOverlap: 20,
              idealEdgeLength: () => 100,
              nodeRepulsion: () => 8000,
            } as cytoscape.LayoutOptions,
      });

      // Register click handler
      cyRef.current.on('tap', 'node', (evt) => {
        const node = evt.target;
        const nodeId = node.id();
        const nodeData: GraphNode = {
          id: nodeId,
          label: node.data('label'),
          properties: {},
        };
        // Find the original node data from props
        const original = nodes.find((n) => n.id === nodeId);
        if (original) {
          nodeData.properties = original.properties;
          nodeData.label = original.label;
        }
        onNodeClick?.(nodeId, nodeData);
      });

      // Deselect on background tap
      cyRef.current.on('tap', (evt) => {
        if (evt.target === cyRef.current) {
          onNodeClick?.('', { id: '', label: '', properties: {} });
        }
      });

      return () => {
        cyRef.current?.destroy();
        cyRef.current = null;
      };
    }, [nodes, edges, layoutMode]);

    // Update selected/query-highlight node styling
    const updateSelection = useCallback(() => {
      const cy = cyRef.current;
      if (!cy) return;
      cy.nodes().removeClass('selected');
      cy.nodes().removeClass('query-highlighted');
      cy.nodes().removeClass('focused');
      cy.edges().removeClass('highlighted');
      cy.edges().removeClass('focused');
      if (selectedNodeId) {
        cy.getElementById(selectedNodeId).addClass('selected');
      }
      if (highlightedNodeIds.length > 0 || highlightedNodeLabels.length > 0) {
        const highlightedIdSet = new Set(highlightedNodeIds);
        const highlightedLabelSet = new Set(highlightedNodeLabels);
        cy.nodes().forEach((node) => {
          const original = nodes.find((n) => n.id === node.id());
          if (!original) return;
          if (highlightedIdSet.has(original.id) || highlightedLabelSet.has(original.label)) {
            node.addClass('query-highlighted');
          }
        });
      }
      if (highlightedEdgeTypes.length > 0) {
        const highlightedEdgeSet = new Set(highlightedEdgeTypes);
        cy.edges().forEach((edge) => {
          const edgeLabel = String(edge.data('label') || '');
          if (highlightedEdgeSet.has(edgeLabel)) {
            edge.addClass('highlighted');
          }
        });
      }
      if (focusedNodeIds.length > 0) {
        const focusedSet = new Set(focusedNodeIds);
        cy.nodes().forEach((node) => {
          if (focusedSet.has(node.id())) {
            node.addClass('focused');
          }
        });
      }
      if (focusedEdge) {
        cy.edges().forEach((edge) => {
          const source = String(edge.data('source') || '');
          const target = String(edge.data('target') || '');
          const label = String(edge.data('label') || '');
          if (source === focusedEdge.source && target === focusedEdge.target && label === focusedEdge.type) {
            edge.addClass('focused');
          }
        });
      }
    }, [
      selectedNodeId,
      highlightedNodeIds,
      highlightedNodeLabels,
      highlightedEdgeTypes,
      focusedNodeIds,
      focusedEdge,
      nodes,
    ]);

    useEffect(() => {
      updateSelection();
    }, [
      updateSelection,
      highlightedNodeIds,
      highlightedNodeLabels,
      highlightedEdgeTypes,
      focusedNodeIds,
      focusedEdge,
      nodes,
      edges,
    ]);

    return (
      <div
        ref={containerRef}
        className="w-full h-full bg-slate-900 rounded-lg border border-slate-700"
      />
    );
  }
);

CytoscapeGraph.displayName = 'CytoscapeGraph';
export default CytoscapeGraph;
