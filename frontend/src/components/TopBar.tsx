import { Link, useLocation } from 'react-router-dom';

export default function TopBar() {
  const { pathname } = useLocation();

  const linkClass = (path: string) =>
    `px-4 py-2 rounded text-sm font-medium transition-colors ${
      pathname === path
        ? 'bg-slate-700 text-white'
        : 'text-slate-300 hover:bg-slate-700/50'
    }`;

  return (
    <header className="bg-slate-800 border-b border-slate-700 px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-6">
        <h1 className="text-lg font-bold text-white tracking-wide">DODGE</h1>
        <nav className="flex gap-2">
          <Link to="/" className={linkClass('/')}>Explorer</Link>
          <Link to="/ingest" className={linkClass('/ingest')}>Ingestion</Link>
        </nav>
      </div>
    </header>
  );
}
