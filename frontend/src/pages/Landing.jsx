import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { applyWaitlist, getDemoTransactions, getStats } from '../api.js';
import RiskBadge from '../components/RiskBadge.jsx';

function short(value) {
  return value ? `${value.slice(0, 10)}...${value.slice(-6)}` : '0x...';
}

export default function Landing() {
  const [stats, setStats] = useState({ protocols_monitored: 0, transactions_scored: 0, alerts_fired: 0 });
  const [feed, setFeed] = useState([]);
  const [form, setForm] = useState({ name: '', email: '', project: '', twitter: '', goal: '' });
  const [message, setMessage] = useState('');

  useEffect(() => {
    getStats().then(setStats).catch(() => {});
    const loadFeed = () => getDemoTransactions().then(setFeed).catch(() => {});
    loadFeed();
    const id = setInterval(loadFeed, 10000);
    return () => clearInterval(id);
  }, []);

  async function submit(event) {
    event.preventDefault();
    setMessage('');
    try {
      const result = await applyWaitlist(form);
      setMessage(result.message);
      setForm({ name: '', email: '', project: '', twitter: '', goal: '' });
    } catch (error) {
      setMessage(error.message || "You're already on the list. We'll be in touch.");
    }
  }

  return (
    <main className="landing">
      <section className="landing-hero">
        <nav className="landing-nav">
          <span className="wordmark">TALOSLY</span>
          <div>
            <Link to="/dashboard" className="nav-link">View Demo</Link>
            <a href="#apply" className="nav-link primary-link">Apply</a>
          </div>
        </nav>
        <div className="hero-grid">
          <div>
            <p className="panel-label">DeFi Security, Automated.</p>
            <h1>AI monitors your protocol 24/7.</h1>
            <p className="hero-copy">Scores every transaction 0-100. Fires alerts before the hack completes.</p>
            <div className="hero-actions">
              <a href="#apply" className="button-link">Apply for Beta Access</a>
              <Link to="/dashboard" className="nav-link">View Demo {'->'}</Link>
            </div>
            <p className="stat-line">
              Monitoring {stats.protocols_monitored} protocols · {stats.transactions_scored} transactions scored · {stats.alerts_fired} alerts fired
            </p>
          </div>
          <div className="terminal-panel">
            <div className="terminal-title">LIVE FEED</div>
            {(feed.length ? feed : [
              { id: 1, tx_hash: '0xabc0000000000000000000000000000000000def', value_eth: 0.5, risk_score: 12 },
              { id: 2, tx_hash: '0x1230000000000000000000000000000000000456', value_eth: 142.3, risk_score: 89 },
              { id: 3, tx_hash: '0xdef0000000000000000000000000000000000789', value_eth: 0.01, risk_score: 8 }
            ]).slice(0, 10).map((tx) => (
              <div className="feed-row" key={tx.id || tx.tx_hash}>
                <span>{short(tx.tx_hash)}</span>
                <span>{Number(tx.value_eth || 0).toFixed(3)} ETH</span>
                <RiskBadge score={tx.risk_score} />
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="landing-band two-col">
        <div>
          <h2>$17B stolen from DeFi in 2025.</h2>
          <p>Most protocols have zero automated monitoring. By the time you see it on Twitter, it's over.</p>
        </div>
        <div>
          <h2>Your protocol needs someone watching.</h2>
          <p>Euler lost $197M in one transaction. Ronin lost $625M and took days to notice.</p>
        </div>
      </section>

      <section className="landing-band steps">
        <article><span>01.</span><h3>Connect</h3><p>Add your contract address. Takes 30 seconds.</p></article>
        <article><span>02.</span><h3>Monitor</h3><p>Talosly watches every transaction 24/7 via AI.</p></article>
        <article><span>03.</span><h3>Alert</h3><p>Risk score above 70 triggers Telegram in seconds.</p></article>
      </section>

      <section className="landing-band quote">
        <p>"Finally, monitoring that doesn't require a $30K/yr security contract."</p>
        <span>— DeFi Founder, private beta</span>
      </section>

      <section className="landing-band apply-section" id="apply">
        <div>
          <h2>Apply for Beta</h2>
          <p>Free during beta. No credit card.</p>
        </div>
        <form className="beta-form" onSubmit={submit}>
          <input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input placeholder="Email" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <input placeholder="Protocol / Project" value={form.project} onChange={(e) => setForm({ ...form, project: e.target.value })} />
          <input placeholder="Twitter/X handle" value={form.twitter} onChange={(e) => setForm({ ...form, twitter: e.target.value })} />
          <textarea placeholder="What are you trying to protect?" value={form.goal} onChange={(e) => setForm({ ...form, goal: e.target.value })} />
          <button>Submit Application</button>
          {message && <div className="form-message">{message}</div>}
        </form>
      </section>

      <footer className="landing-footer">
        <span className="wordmark">TALOSLY</span>
        <span>DeFi Security Alert System — Free Beta</span>
        <span>© 2026 Talosly. Protecting DeFi, one protocol at a time.</span>
      </footer>
    </main>
  );
}
