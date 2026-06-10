import { Link, useLocation } from 'react-router-dom';

export default function Nav({ online, lastUpdated }) {
  const { pathname } = useLocation();

  function active(path) {
    if (path === '/agents') return pathname.startsWith('/agents') ? 'active' : '';
    return pathname === path ? 'active' : '';
  }

  return (
    <header className="topbar">
      <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
        <Link to="/" className="wordmark" style={{ textDecoration: 'none' }}>
          Talosly
        </Link>
        <nav style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <Link to="/agents"    className={`nav-link ${active('/agents')}`}>Agent Guardian</Link>
          <Link to="/dashboard" className={`nav-link ${active('/dashboard')}`}>Protocols</Link>
        </nav>
      </div>
      <div className="header-right">
        <div className="status">
          <span className={`status-dot ${online ? 'online' : ''}`} aria-hidden="true" />
          <span>{online ? 'online' : 'offline'}</span>
        </div>
        {lastUpdated && (
          <span className="last-updated">{lastUpdated}</span>
        )}
        <Link to="/admin" className={`nav-link ${active('/admin')}`} style={{ fontSize: 12 }}>Admin</Link>
      </div>
    </header>
  );
}
