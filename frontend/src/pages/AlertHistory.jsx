import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getAlerts, getAlertStats, submitAlertFeedback } from '../api.js';
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
  const [savingFeedback, setSavingFeedback] = useState({});

  useEffect(() => {
    getAlerts(200).then(setAlerts).catch(() => setAlerts([]));
    getAlertStats().then(setStats).catch(() => {});
  }, []);

  const filtered = useMemo(
    () => alerts.filter((alert) => alert.risk_score >= Number(min) && alert.risk_score <= Number(max)),
    [alerts, min, max]
  );

  async function handleFeedback(alertId, feedback) {
    setSavingFeedback((current) => ({ ...current, [alertId]: true }));
    try {
      await submitAlertFeedback(alertId, feedback);
      setAlerts((current) =>
        current.map((alert) => (alert.id === alertId ? { ...alert, confirmed_threat: feedback } : alert))
      );
    } finally {
      setSavingFeedback((current) => ({ ...current, [alertId]: false }));
    }
  }

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
                <th>Feedback</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr><td colSpan="7" className="empty-row">No high-risk alerts detected across monitored protocols.</td></tr>
              ) : filtered.map((alert) => (
                <tr key={alert.id}>
                  <td>{alert.protocol_name}</td>
                  <td className="mono">{shorten(alert.tx_hash)}</td>
                  <td><RiskBadge score={alert.risk_score} /></td>
                  <td>{alert.risk_summary}</td>
                  <td>{alert.created_at}</td>
                  <td>{alert.telegram_sent ? '✓' : '×'}</td>
                  <td>
                    <div className="feedback-actions" aria-label={`Feedback for alert ${alert.id}`}>
                      <button
                        type="button"
                        className={`feedback-button positive ${alert.confirmed_threat === true ? 'selected' : ''}`}
                        aria-label="Mark alert as useful"
                        title="Useful alert"
                        disabled={Boolean(savingFeedback[alert.id])}
                        onClick={() => handleFeedback(alert.id, true)}
                      >
                        👍
                      </button>
                      <button
                        type="button"
                        className={`feedback-button negative ${alert.confirmed_threat === false ? 'selected' : ''}`}
                        aria-label="Mark alert as not useful"
                        title="Not useful"
                        disabled={Boolean(savingFeedback[alert.id])}
                        onClick={() => handleFeedback(alert.id, false)}
                      >
                        👎
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
