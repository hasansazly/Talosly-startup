import { Link } from 'react-router-dom';

export default function Header({ online, lastUpdated }) {
  return (
    <header className="topbar">
      <div>
        <div className="wordmark">TALOSLY</div>
        <div className="subtitle">DeFi Security Monitor</div>
      </div>
      <div className="header-right">
        <Link to="/" className="nav-link">Home</Link>
        <Link to="/alerts" className="nav-link">Alert History</Link>
        <div className="status">
          <span className={`status-dot ${online ? 'online' : ''}`} />
          <span>{online ? 'worker running' : 'offline'}</span>
        </div>
        <div className="last-updated">{lastUpdated ? `Updated ${lastUpdated}` : 'Waiting for data'}</div>
      </div>
    </header>
  );
}
