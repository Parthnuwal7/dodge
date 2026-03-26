import type { GraphNode } from '../types';

const LABEL_COLORS: Record<string, string> = {
  Customer: '#6366f1',
  Address: '#f59e0b',
  SalesOrder: '#10b981',
  SalesOrderItem: '#ef4444',
  Delivery: '#8b5cf6',
  DeliveryItem: '#ec4899',
  Invoice: '#14b8a6',
  InvoiceItem: '#f97316',
  JournalEntry: '#3b82f6',
  Payment: '#84cc16',
  Product: '#f59e0b',
  Plant: '#6366f1',
};

interface Props {
  node: GraphNode;
  expanded: boolean;
  onExpand: () => void;
  onClose: () => void;
  loading?: boolean;
}

export default function NodeDetailPanel({ node, expanded, onExpand, onClose, loading }: Props) {
  const badgeColor = LABEL_COLORS[node.label] || '#6366f1';

  return (
    <div className="bg-slate-800 border-l border-slate-700 w-80 flex-shrink-0 flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className="inline-block w-3 h-3 rounded-full"
            style={{ backgroundColor: badgeColor }}
          />
          <h3 className="text-sm font-semibold text-slate-200">{node.label}</h3>
        </div>
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-slate-200 text-lg leading-none"
          title="Close"
        >
          &times;
        </button>
      </div>

      {/* Properties */}
      <div className="flex-1 overflow-y-auto p-4">
        <table className="w-full text-xs">
          <tbody>
            {Object.entries(node.properties).map(([key, value]) => (
              <tr key={key} className="border-b border-slate-700/50">
                <td className="py-1.5 pr-3 text-slate-400 font-medium whitespace-nowrap align-top">
                  {key}
                </td>
                <td className="py-1.5 text-slate-200 break-all">
                  {String(value ?? '')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Actions */}
      <div className="p-3 border-t border-slate-700">
        <button
          onClick={onExpand}
          disabled={expanded || loading}
          className={`w-full text-sm py-2 rounded-lg font-medium transition-colors ${
            expanded
              ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
              : loading
                ? 'bg-indigo-600/50 text-indigo-200 cursor-wait'
                : 'bg-indigo-600 hover:bg-indigo-500 text-white'
          }`}
        >
          {loading ? 'Loading...' : expanded ? 'Neighbors Expanded' : 'Expand Neighbors'}
        </button>
      </div>
    </div>
  );
}
