import { useState } from 'react';
import { previewSchema, buildGraph, clearGraph } from '../api/client';
import type { GraphSchema, BuildReport } from '../types';

type Step = 'idle' | 'loading' | 'preview' | 'building' | 'clearing' | 'done';

export default function Ingestion() {
  const [step, setStep] = useState<Step>('idle');
  const [schema, setSchema] = useState<GraphSchema | null>(null);
  const [schemaText, setSchemaText] = useState('');
  const [report, setReport] = useState<BuildReport | null>(null);
  const [clearExisting, setClearExisting] = useState(false);
  const [error, setError] = useState('');
  const [clearMessage, setClearMessage] = useState('');

  const handlePreview = async () => {
    setError('');
    setStep('loading');
    try {
      const result = await previewSchema();
      setSchema(result.graph_schema);
      setSchemaText(JSON.stringify(result.graph_schema, null, 2));
      setStep('preview');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Preview failed');
      setStep('idle');
    }
  };

  const handleBuild = async () => {
    setError('');
    try {
      const edited: GraphSchema = JSON.parse(schemaText);
      setStep('building');
      const result = await buildGraph(edited, clearExisting);
      setReport(result.report);
      setStep('done');
    } catch (err: unknown) {
      if (err instanceof SyntaxError) {
        setError('Invalid JSON in schema editor');
      } else {
        setError(err instanceof Error ? err.message : 'Build failed');
      }
      setStep('preview');
    }
  };

  const handleClear = async () => {
    setError('');
    setClearMessage('');
    setStep('clearing');
    try {
      const result = await clearGraph();
      setClearMessage(result.message);
      setStep('idle');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Clear failed');
      setStep('idle');
    }
  };

  const handleReset = () => {
    setStep('idle');
    setSchema(null);
    setSchemaText('');
    setReport(null);
    setError('');
    setClearMessage('');
  };

  return (
    <div className="flex-1 overflow-y-auto p-8 max-w-5xl mx-auto w-full">
      <h1 className="text-2xl font-bold text-slate-100 mb-2">Data Ingestion</h1>
      <p className="text-slate-400 text-sm mb-8">
        Two-step process: preview the inferred schema, review/edit it, then build the graph.
      </p>

      {error && (
        <div className="bg-red-900/30 border border-red-700 rounded-lg px-4 py-3 text-red-300 text-sm mb-6">
          {error}
        </div>
      )}

      {clearMessage && (
        <div className="bg-green-900/30 border border-green-700 rounded-lg px-4 py-3 text-green-300 text-sm mb-6">
          {clearMessage}
        </div>
      )}

      {/* Step 1: Preview */}
      {step === 'idle' && (
        <div className="space-y-4">
          <div className="bg-slate-800 rounded-lg border border-slate-700 p-6">
            <h2 className="text-lg font-semibold text-slate-200 mb-2">
              Step 1: Preview Schema
            </h2>
            <p className="text-slate-400 text-sm mb-4">
              Loads JSONL data from the configured directory, infers ID columns and
              relationships. No data is written to Neo4j.
            </p>
            <button
              onClick={handlePreview}
              className="bg-indigo-600 hover:bg-indigo-500 text-white px-6 py-2 rounded-lg text-sm font-medium transition-colors"
            >
              Run Preview
            </button>
          </div>

          <div className="bg-slate-800 rounded-lg border border-slate-700 p-6">
            <h2 className="text-lg font-semibold text-slate-200 mb-2">
              Database Management
            </h2>
            <p className="text-slate-400 text-sm mb-4">
              Clear all nodes and relationships from Neo4j before re-ingesting.
              Use this when you need to start fresh (e.g. schema changes, Aura tier limits).
            </p>
            <button
              onClick={handleClear}
              className="bg-red-600 hover:bg-red-500 text-white px-6 py-2 rounded-lg text-sm font-medium transition-colors"
            >
              Clear Database
            </button>
          </div>
        </div>
      )}

      {step === 'clearing' && (
        <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 text-center">
          <p className="text-slate-300 animate-pulse">
            Clearing database...
          </p>
        </div>
      )}

      {step === 'loading' && (
        <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 text-center">
          <p className="text-slate-300 animate-pulse">
            Inferring schema from data...
          </p>
        </div>
      )}

      {/* Step 2: Review & Edit */}
      {step === 'preview' && schema && (
        <div className="space-y-6">
          <div className="bg-slate-800 rounded-lg border border-slate-700 p-6">
            <h2 className="text-lg font-semibold text-slate-200 mb-1">
              Step 2: Review Schema
            </h2>
            <p className="text-slate-400 text-sm mb-4">
              {schema.nodes.length} node types, {schema.edges.length} edge types
              detected. Edit the JSON below if needed.
            </p>

            {/* Summary cards */}
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div className="bg-slate-900 rounded-lg p-4 border border-slate-700">
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">
                  Nodes
                </h3>
                <div className="space-y-1 max-h-48 overflow-y-auto">
                  {schema.nodes.map((n) => (
                    <div key={n.label} className="text-sm text-slate-300 flex justify-between">
                      <span>{n.label}</span>
                      <span className="text-slate-500 text-xs font-mono">
                        id: {Array.isArray(n.id_field) ? n.id_field.join(', ') : n.id_field}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="bg-slate-900 rounded-lg p-4 border border-slate-700">
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">
                  Edges
                </h3>
                <div className="space-y-1 max-h-48 overflow-y-auto">
                  {schema.edges.map((e, i) => (
                    <div key={i} className="text-sm text-slate-300">
                      <span className="text-slate-400">{e.from_node}</span>
                      <span className="text-indigo-400 mx-1">-[{e.type}]-&gt;</span>
                      <span className="text-slate-400">{e.to_node}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* JSON editor */}
            <textarea
              value={schemaText}
              onChange={(e) => setSchemaText(e.target.value)}
              rows={20}
              className="w-full bg-slate-900 text-slate-300 text-xs font-mono rounded-lg p-4 border border-slate-600 focus:outline-none focus:border-indigo-500 resize-y"
              spellCheck={false}
            />
          </div>

          <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 flex items-center justify-between">
            <label className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={clearExisting}
                onChange={(e) => setClearExisting(e.target.checked)}
                className="rounded border-slate-600"
              />
              Clear existing graph before building
            </label>
            <div className="flex gap-3">
              <button
                onClick={handleReset}
                className="text-slate-400 hover:text-slate-200 px-4 py-2 text-sm transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleBuild}
                className="bg-green-600 hover:bg-green-500 text-white px-6 py-2 rounded-lg text-sm font-medium transition-colors"
              >
                Build Graph
              </button>
            </div>
          </div>
        </div>
      )}

      {step === 'building' && (
        <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 text-center">
          <p className="text-slate-300 animate-pulse">
            Building graph in Neo4j...
          </p>
        </div>
      )}

      {/* Step 3: Report */}
      {step === 'done' && report && (
        <div className="space-y-6">
          <div className="bg-slate-800 rounded-lg border border-slate-700 p-6">
            <h2 className="text-lg font-semibold text-green-400 mb-4">
              Build Complete
            </h2>

            <div className="grid grid-cols-2 gap-4 mb-4">
              <div className="bg-slate-900 rounded-lg p-4 border border-slate-700">
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">
                  Nodes Created
                </h3>
                <div className="space-y-1">
                  {Object.entries(report.nodes_created).map(([label, count]) => (
                    <div key={label} className="text-sm text-slate-300 flex justify-between">
                      <span>{label}</span>
                      <span className="text-slate-400">{count.toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="bg-slate-900 rounded-lg p-4 border border-slate-700">
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">
                  Edges Created
                </h3>
                <div className="space-y-1 max-h-48 overflow-y-auto">
                  {Object.entries(report.edges_created).map(([type, count]) => (
                    <div key={type} className="text-sm text-slate-300 flex justify-between">
                      <span>{type}</span>
                      <span className="text-slate-400">{count.toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {report.errors.length > 0 && (
              <div className="bg-red-900/20 border border-red-800 rounded-lg p-4">
                <h3 className="text-xs font-semibold text-red-400 uppercase tracking-wide mb-2">
                  Errors
                </h3>
                {report.errors.map((err, i) => (
                  <p key={i} className="text-sm text-red-300">{err}</p>
                ))}
              </div>
            )}
          </div>

          <button
            onClick={handleReset}
            className="bg-indigo-600 hover:bg-indigo-500 text-white px-6 py-2 rounded-lg text-sm font-medium transition-colors"
          >
            Start New Ingestion
          </button>
        </div>
      )}
    </div>
  );
}
