import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getAlerts, getAlertStats } from '../api.js';
import RiskBadge from '../components/RiskBadge.jsx';

function shorten(value) {
  if (!value) return '—';
  return `${value.slice(0, 10)}...${value.slice(-6)}`;
}

export default function AlertHistory() {
  const [alerts, setAlerts] = useState([]);
  const [stats, setStats] = useState({ today: 0, this_week: 0, all_time: 0 });
  const [min, setMin] = useState(0);
  const [max, setMax] = useState(100);

  useEffect(() => {
    getAlerts(200).then(setAlerts).catch(() => setAlerts([]));
    getAlertStats().then(setStats).catch(() => {});
  }, []);

  const filtered = useMemo(
    () => alerts.filter((alert) => alert.risk_score >= Number(min) && alert.risk_score <= Number(max)),
    [alerts, min, max]
  );

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <div className="wordmark">TALOSLY</div>
          <div className="subtitle">Alert History</div>
        </div>
        <Link className="nav-link" to="/">Back to Dashboard</Link>
      </header>
      <section className="stats-row">
        <div><span>Today</span><strong>{stats.today}</strong></div>
        <div><span>This Week</span><strong>{stats.this_week}</strong></div>
        <div><span>All Time</span><strong>{stats.all_time}</strong></div>
      </section>
      <section className="panel table-panel">
        <div className="filters">
          <label>Min <input type="number" min="0" max="100" value={min} onChange={(event) => setMin(event.target.value)} /></label>
          <label>Max <input type="number" min="0" max="100" value={max} onChange={(event) => setMax(event.target.value)} /></label>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Protocol</th>
                <th>TX Hash</th>
                <th>Risk Score</th>
                <th>Summary</th>
                <th>Time</th>
                <th>Telegram</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr><td colSpan="6" className="empty-row">No alerts match this range</td></tr>
              ) : filtered.map((alert) => (
                <tr key={alert.id}>
                  <td>{alert.protocol_name}</td>
                  <td className="mono">{shorten(alert.tx_hash)}</td>
                  <td><RiskBadge score={alert.risk_score} /></td>
                  <td>{alert.risk_summary}</td>
                  <td>{alert.created_at}</td>
                  <td>{alert.telegram_sent ? '✓' : '×'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
