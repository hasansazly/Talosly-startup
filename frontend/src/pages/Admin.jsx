import { useEffect, useState } from 'react';
import { approveWaitlist, getAdminKeys, getAdminMetrics, getAdminWaitlist, rejectWaitlist, revokeKey } from '../api.js';

export default function Admin() {
  const [secret, setSecret] = useState(sessionStorage.getItem('talosly_admin_secret') || '');
  const [metrics, setMetrics] = useState(null);
  const [waitlist, setWaitlist] = useState({ counts: {}, items: [] });
  const [keys, setKeys] = useState([]);
  const [shownKey, setShownKey] = useState('');

  async function load() {
    sessionStorage.setItem('talosly_admin_secret', secret);
    setMetrics(await getAdminMetrics());
    setWaitlist(await getAdminWaitlist());
    setKeys(await getAdminKeys());
  }

  useEffect(() => {
    if (secret) load().catch(() => {});
  }, []);

  async function approve(id) {
    const result = await approveWaitlist(id);
    setShownKey(result.api_key);
    await load();
  }

  if (!secret || !metrics) {
    return (
      <main className="app-shell">
        <section className="panel key-panel">
          <h1>Talosly Admin</h1>
          <form className="add-form" onSubmit={(event) => { event.preventDefault(); load(); }}>
            <input type="password" value={secret} onChange={(event) => setSecret(event.target.value)} placeholder="ADMIN_SECRET" required />
            <button>Unlock</button>
          </form>
        </section>
      </main>
    );
  }

  const overview = metrics.overview || {};
  return (
    <main className="app-shell admin-shell">
      <header className="topbar"><div><div className="wordmark">TALOSLY</div><div className="subtitle">Admin</div></div></header>
      <section className="stats-row">
        <div><span>Protocols</span><strong>{overview.protocols_monitored || 0}</strong></div>
        <div><span>Transactions</span><strong>{overview.transactions_scored_total || 0}</strong></div>
        <div><span>Alerts</span><strong>{overview.alerts_fired_total || 0}</strong></div>
        <div><span>Active Keys</span><strong>{overview.active_api_keys || 0}</strong></div>
        <div><span>Pending</span><strong>{overview.waitlist_pending || 0}</strong></div>
        <div><span>Requests Today</span><strong>{overview.requests_today || 0}</strong></div>
      </section>
      {shownKey && (
        <section className="panel key-modal">
          <h2>API key shown once</h2>
          <p className="mono">{shownKey}</p>
          <button onClick={() => navigator.clipboard.writeText(shownKey)}>Copy</button>
        </section>
      )}
      <section className="panel table-panel">
        <h2>Waitlist Queue</h2>
        <div className="table-wrap"><table><thead><tr><th>Name</th><th>Email</th><th>Project</th><th>Twitter</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>{waitlist.items.map((item) => (
            <tr key={item.id}><td>{item.name}</td><td>{item.email}</td><td>{item.project}</td><td>{item.twitter}</td><td>{item.status}</td><td>
              {item.status === 'pending' && <><button onClick={() => approve(item.id)}>Approve</button> <button onClick={async () => { await rejectWaitlist(item.id); await load(); }}>Reject</button></>}
            </td></tr>
          ))}</tbody></table></div>
      </section>
      <section className="panel table-panel">
        <h2>Active API Keys</h2>
        <div className="table-wrap"><table><thead><tr><th>Prefix</th><th>Name</th><th>Today</th><th>Total</th><th>Last Used</th><th></th></tr></thead>
          <tbody>{keys.map((key) => (
            <tr key={key.id}><td className="mono">{key.key_prefix}</td><td>{key.name}</td><td>{key.requests_today}</td><td>{key.requests_total}</td><td>{key.last_used_at}</td><td><button onClick={async () => { await revokeKey(key.id); await load(); }}>Revoke</button></td></tr>
          ))}</tbody></table></div>
      </section>
    </main>
  );
}
