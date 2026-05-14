import { Link } from 'react-router-dom';

export default function Header({ online, lastUpdated, onDemoAlert }) {
  return (
    <header className="topbar">
      <div>
        <div className="wordmark">TALOSLY</div>
        <div className="subtitle">DeFi Security Monitor</div>
      </div>
      <div className="header-right">
        <Link to="/" className="nav-link">Home</Link>
        <Link to="/dashboard" className="nav-link">Dashboard</Link>
        <Link to="/replay" className="nav-link">Replay</Link>
        <Link to="/alerts" className="nav-link">Alert History</Link>
        {onDemoAlert && <button type="button" className="nav-action" onClick={onDemoAlert}>▶ Run Demo Alert</button>}
        <div className="status">
          <span className={`status-dot ${online ? 'online' : ''}`} />
          <span>{online ? 'worker running' : 'offline'}</span>
        </div>
        <div className="last-updated">{lastUpdated ? `Updated ${lastUpdated}` : 'Waiting for data'}</div>
      </div>
    </header>
  );
}
