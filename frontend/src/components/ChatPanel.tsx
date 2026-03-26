import { useEffect, useRef, useState } from 'react';
import type { AskResponse, ChatHistoryItem } from '../types';
import { askQuestion, clearChatHistory, getChatHistory, getChatLoggerStatus } from '../api/client';

interface Message {
  role: 'user' | 'assistant';
  text: string;
  data?: AskResponse;
}

interface Props {
  onResult: (result: AskResponse) => void;
}

const SESSION_STORAGE_KEY = 'dodge_chat_session_id';

function createSessionId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `sess-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function getOrCreateSessionId(): string {
  const existing = localStorage.getItem(SESSION_STORAGE_KEY);
  if (existing) return existing;
  const created = createSessionId();
  localStorage.setItem(SESSION_STORAGE_KEY, created);
  return created;
}

function buildAskResponseFromHistory(item: ChatHistoryItem): AskResponse {
  return {
    answer: item.answer,
    explanation: item.explanation,
    query_used: item.query_used,
    nodes: [],
    edges: [],
    data: [],
    metadata: item.metadata || {},
  };
}

function DataTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (rows.length === 0) return null;

  // Get column names from first row, filter out large objects
  const columns = Object.keys(rows[0]).filter((key) => {
    const val = rows[0][key];
    return typeof val !== 'object' || val === null;
  });

  if (columns.length === 0) return null;

  return (
    <div className="mt-2 max-h-48 overflow-auto rounded border border-slate-600">
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-slate-800 sticky top-0">
            {columns.map((col) => (
              <th
                key={col}
                className="px-2 py-1 text-left text-slate-400 font-medium whitespace-nowrap"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-slate-700/50 hover:bg-slate-700/30">
              {columns.map((col) => (
                <td key={col} className="px-2 py-1 text-slate-300 whitespace-nowrap">
                  {String(row[col] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ChatPanel({ onResult }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string>('');
  const [chatStoreStatus, setChatStoreStatus] = useState<string>('Checking chat storage...');
  const onResultRef = useRef(onResult);

  useEffect(() => {
    onResultRef.current = onResult;
  }, [onResult]);

  useEffect(() => {
    const currentSessionId = getOrCreateSessionId();
    setSessionId(currentSessionId);

    getChatLoggerStatus()
      .then((status) => {
        if (!status.enabled) {
          setChatStoreStatus('Chat history storage disabled');
          return;
        }
        if (!status.connected) {
          setChatStoreStatus('Chat history storage unavailable');
          return;
        }

        setChatStoreStatus('Chat history storage connected');
        return getChatHistory(currentSessionId, 200).then((history) => {
          const restored: Message[] = [];
          history.items.forEach((item) => {
            if (item.question) {
              restored.push({ role: 'user', text: item.question });
            }

            const assistantText = item.answer || (item.error ? `Error: ${item.error}` : 'No response');
            const data = item.status === 'success' ? buildAskResponseFromHistory(item) : undefined;
            restored.push({ role: 'assistant', text: assistantText, data });
          });

          setMessages(restored);

          const lastSuccess = [...history.items].reverse().find((item) => item.status === 'success' && !!item.query_used);
          if (lastSuccess) {
            onResultRef.current(buildAskResponseFromHistory(lastSuccess));
          }
        });
      })
      .catch(() => {
        setChatStoreStatus('Chat history storage unavailable');
      });
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const question = input.trim();
    if (!question || loading) return;

    setInput('');
    setMessages((prev) => [...prev, { role: 'user', text: question }]);
    setLoading(true);

    try {
      const result = await askQuestion(question, undefined, sessionId || getOrCreateSessionId());
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          text: result.answer,
          data: result,
        },
      ]);
      onResult(result);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Query failed';
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', text: `Error: ${message}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleQuit = async () => {
    const currentSessionId = sessionId || localStorage.getItem(SESSION_STORAGE_KEY) || '';
    if (currentSessionId) {
      try {
        await clearChatHistory(currentSessionId);
      } catch {
        // Keep local reset behavior even if remote clear fails.
      }
    }

    const newSessionId = createSessionId();
    localStorage.setItem(SESSION_STORAGE_KEY, newSessionId);
    setSessionId(newSessionId);
    setMessages([]);
  };

  return (
    <div className="flex flex-col h-full bg-slate-800 border-l border-slate-700">
      <div className="px-4 py-3 border-b border-slate-700">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-slate-200">Query Chat</h2>
          <button
            type="button"
            onClick={handleQuit}
            className="text-xs px-2 py-1 rounded border border-slate-600 text-slate-300 hover:bg-slate-700"
          >
            Quit
          </button>
        </div>
        <p className="text-[11px] text-slate-500 mt-1">{chatStoreStatus}</p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 && (
          <p className="text-slate-500 text-sm text-center mt-8">
            Ask a question about your graph...
          </p>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`text-sm rounded-lg px-3 py-2 ${
              msg.role === 'user'
                ? 'bg-indigo-600/20 text-indigo-200 ml-6'
                : 'bg-slate-700 text-slate-200 mr-6'
            }`}
          >
            <p>{msg.text}</p>
            {msg.data && (
              <div className="mt-2 text-xs text-slate-400 space-y-1">
                <p>{msg.data.explanation}</p>
                <p className="font-mono bg-slate-800 rounded px-2 py-1 break-all">
                  {msg.data.query_used}
                </p>
                <p>
                  {msg.data.data.length > 0
                    ? `${msg.data.data.length} results`
                    : `${msg.data.nodes.length} nodes, ${msg.data.edges.length} edges`}
                  {msg.data.metadata.execution_time_ms != null &&
                    ` | ${String(msg.data.metadata.execution_time_ms)}ms`}
                </p>
                {msg.data.data.length > 0 && (
                  <DataTable rows={msg.data.data} />
                )}
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div className="text-sm text-slate-400 animate-pulse">Thinking...</div>
        )}
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="p-3 border-t border-slate-700">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="e.g. How many sales orders are there?"
            className="flex-1 bg-slate-900 text-slate-200 text-sm rounded-lg px-3 py-2 border border-slate-600 focus:outline-none focus:border-indigo-500 placeholder-slate-500"
            disabled={loading}
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-600 text-white text-sm px-4 py-2 rounded-lg transition-colors"
          >
            Ask
          </button>
        </div>
      </form>
    </div>
  );
}
