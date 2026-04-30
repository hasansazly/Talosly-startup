import { useEffect, useState } from 'react';
import { approveWaitlist, createAdminKey, getAdminKeys, getAdminMetrics, getAdminWaitlist, rejectWaitlist, revokeKey, validateAdminKey } from '../api.js';

export default function Admin() {
  const [secret, setSecret] = useState(sessionStorage.getItem('talosly_admin_secret') || '');
  const [metrics, setMetrics] = useState(null);
  const [waitlist, setWaitlist] = useState({ counts: {}, items: [] });
  const [keys, setKeys] = useState([]);
  const [shownKey, setShownKey] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [keyToValidate, setKeyToValidate] = useState('');

  async function load() {
    try {
      setError('');
      setNotice('');
      sessionStorage.setItem('talosly_admin_secret', secret);
      const nextMetrics = await getAdminMetrics();
      setMetrics(nextMetrics);
      try {
        setWaitlist(await getAdminWaitlist());
      } catch {
        setWaitlist({ counts: {}, items: [] });
      }
      setKeys(await getAdminKeys());
    } catch (err) {
      setError(err.message || 'Admin unlock failed');
    }
  }

  useEffect(() => {
    if (secret) load().catch(() => {});
  }, []);

  async function approve(id) {
    try {
      setError('');
      const result = await approveWaitlist(id);
      setShownKey(result.api_key);
      await load();
    } catch (err) {
      setError(err.message || 'Approval failed');
    }
  }

  async function copyShownKey() {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(shownKey);
      } else {
        throw new Error('Clipboard API unavailable');
      }
      setNotice('Copied API key');
    } catch {
      setNotice('Copy failed. Select the key text and copy it manually.');
    }
  }

  async function revoke(keyId) {
    try {
      setError('');
      setNotice('');
      await revokeKey(keyId);
      setNotice('API key revoked');
      await load();
    } catch (err) {
      setError(err.message || 'Could not revoke key');
    }
  }

  if (!secret || !metrics) {
    return (
      <main className="app-shell">
        <section className="panel key-panel">
          <h1>Talosly Admin</h1>
          <form className="add-form" onSubmit={(event) => { event.preventDefault(); load(); }}>
            <input type="password" value={secret} onChange={(event) => setSecret(event.target.value)} placeholder="ADMIN_SECRET" required />
            <button>Unlock</button>
            {error && <div className="form-error">{error}</div>}
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
      <section className="panel">
        <h2>Create API Key</h2>
        <button onClick={async () => {
          try {
            setError('');
            setNotice('');
            const result = await createAdminKey('Dev key');
            setShownKey(result.api_key);
            await load();
          } catch (err) {
            setError(err.message || 'Could not create key');
          }
        }}>Create Dev Key</button>
        {error && <div className="form-error">{error}</div>}
        {notice && <div className="form-message">{notice}</div>}
      </section>
      <section className="panel">
        <h2>Validate API Key</h2>
        <form className="add-form" onSubmit={async (event) => {
          event.preventDefault();
          try {
            setError('');
            const result = await validateAdminKey(keyToValidate);
            setNotice(result.valid ? `Valid key: ${result.key_prefix}` : result.message);
          } catch (err) {
            setError(err.message || 'Validation failed');
          }
        }}>
          <input value={keyToValidate} onChange={(event) => setKeyToValidate(event.target.value)} placeholder="tals_..." />
          <button>Validate</button>
        </form>
      </section>
      {shownKey && (
        <section className="panel key-modal">
          <h2>API key shown once</h2>
          <input className="mono key-output" readOnly value={shownKey} onFocus={(event) => event.target.select()} />
          <button onClick={copyShownKey}>Copy</button>
          {notice && <div className="form-message">{notice}</div>}
        </section>
      )}
      <section className="panel table-panel">
        <h2>Waitlist Queue</h2>
        <div className="table-wrap"><table><thead><tr><th>Name</th><th>Email</th><th>Project</th><th>Twitter</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>{waitlist.items.map((item) => (
            <tr key={item.id}><td>{item.name}</td><td>{item.email}</td><td>{item.project}</td><td>{item.twitter}</td><td>{item.status}</td><td>
              {item.status === 'pending' && <><button onClick={() => approve(item.id)}>Approve</button> <button onClick={async () => {
                try {
                  setError('');
                  await rejectWaitlist(item.id);
                  await load();
                } catch (err) {
                  setError(err.message || 'Reject failed');
                }
              }}>Reject</button></>}
            </td></tr>
          ))}</tbody></table></div>
      </section>
      <section className="panel table-panel">
        <h2>Active API Keys</h2>
        <div className="table-wrap"><table><thead><tr><th>Prefix</th><th>Name</th><th>Status</th><th>Today</th><th>Total</th><th>Last Used</th><th></th></tr></thead>
          <tbody>{keys.map((key) => (
            <tr key={key.id}><td className="mono">{key.key_prefix}</td><td>{key.name}</td><td>{key.is_active ? 'Active' : 'Revoked'}</td><td>{key.requests_today}</td><td>{key.requests_total}</td><td>{key.last_used_at}</td><td>{key.is_active && <button onClick={() => revoke(key.id)}>Revoke</button>}</td></tr>
          ))}</tbody></table></div>
        {error && <div className="form-error">{error}</div>}
        {notice && <div className="form-message">{notice}</div>}
      </section>
    </main>
  );
}
