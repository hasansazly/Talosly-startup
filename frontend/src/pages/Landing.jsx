import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { applyWaitlist, getPublicSettings, getStats } from '../api.js';
import RiskBadge from '../components/RiskBadge.jsx';

function short(value) {
  return value ? `${value.slice(0, 10)}...${value.slice(-6)}` : '0x...';
}

export default function Landing() {
  const [stats, setStats] = useState({ transactions_scored: 0, alerts_fired: 0 });
  const [appSettings, setAppSettings] = useState({
    risk_alert_threshold: 70,
    marketing_transactions_scored: 11868,
    marketing_alerts_fired: 10832,
    marketing_alert_latency: '<3s',
  });
  const [form, setForm] = useState({ name: '', email: '', project: '', twitter: '', goal: '' });
  const [message, setMessage] = useState('');

  useEffect(() => {
    getStats().then(setStats).catch(() => {});
    getPublicSettings().then(setAppSettings).catch(() => {});
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

  const marketingTransactions = Number(appSettings.marketing_transactions_scored || 0).toLocaleString();
  const marketingAlerts = Number(appSettings.marketing_alerts_fired || 0).toLocaleString();
  const sampleActions = [
    { id: 1, tx_hash: 'agent://treasury/rebalance', value_eth: 0.5, risk_score: 12 },
    { id: 2, tx_hash: 'agent://ops/new-counterparty', value_eth: 142.3, risk_score: 89 },
    { id: 3, tx_hash: 'agent://market-maker/quote', value_eth: 0.01, risk_score: 8 },
  ];

  return (
    <main className="landing">
      <section className="landing-hero">
        <div aria-hidden="true" style={{
          position: 'absolute', top: '50%', left: '30%', transform: 'translate(-50%,-60%)',
          width: '600px', height: '600px', borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(56,189,248,0.07) 0%, transparent 70%)',
          pointerEvents: 'none', zIndex: 0
        }}></div>
        <nav className="landing-nav">
          <span className="wordmark">TALOSLY</span>
          <div>
            <Link to="/agents" className="nav-link">Open Agents</Link>
            <a href="#apply" className="nav-link primary-link">Apply</a>
          </div>
        </nav>
        <div className="hero-grid">
          <div>
            <div style={{
              display: 'inline-flex', alignItems: 'center', gap: '8px',
              border: '1px solid rgba(56,189,248,0.25)', borderRadius: '100px',
              padding: '5px 14px', marginBottom: '20px',
              fontSize: '11px', letterSpacing: '0.12em', textTransform: 'uppercase',
              color: '#38bdf8', fontFamily: "'Space Mono',monospace"
            }}>
              <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#f87171', display: 'inline-block', animation: 'pulse 1.5s ease-in-out infinite' }}></span>
              Beta · Live Now
            </div>
            <p className="panel-label">Know-Your-Agent, Automated.</p>
            <h1>AI monitors your agents <em>24/7.</em></h1>
            <p className="hero-copy">Scores every agent action 0-100. Flags behavioral breaks before damage spreads.</p>
            <div className="hero-actions">
              <a href="#apply" className="button-link">Apply for Beta Access</a>
              <Link to="/agents" className="nav-link">Open Agents {'->'}</Link>
            </div>
            <p className="stat-line">
              {stats.transactions_scored} actions scored · {stats.alerts_fired} alerts fired
            </p>
          </div>
          <div className="terminal-panel">
            <div style={{ background: '#080c12', borderBottom: '1px solid rgba(56,189,248,0.1)', padding: '10px 14px', display: 'flex', alignItems: 'center', gap: '8px' }} aria-hidden="true">
              <span style={{ width: '10px', height: '10px', borderRadius: '50%', background: 'rgba(248,113,113,0.4)', display: 'inline-block' }}></span>
              <span style={{ width: '10px', height: '10px', borderRadius: '50%', background: 'rgba(251,191,36,0.4)', display: 'inline-block' }}></span>
              <span style={{ width: '10px', height: '10px', borderRadius: '50%', background: 'rgba(52,211,153,0.4)', display: 'inline-block' }}></span>
              <span style={{ fontFamily: "'Space Mono',monospace", fontSize: '10px', color: '#64748b', marginLeft: '8px', letterSpacing: '0.06em' }}>talosly://live-feed</span>
            </div>
            <div className="terminal-title">LIVE FEED</div>
            {sampleActions.map((tx) => (
              <div className="feed-row" key={tx.id || tx.tx_hash}>
                <span>{short(tx.tx_hash)}</span>
                <span>{Number(tx.value_eth || 0).toFixed(3)} ETH</span>
                <RiskBadge score={tx.risk_score} />
              </div>
            ))}
          </div>
        </div>
      </section>

      <div style={{ borderTop: '1px solid rgba(56,189,248,0.08)', borderBottom: '1px solid rgba(56,189,248,0.08)', padding: '14px 0', overflow: 'hidden', background: 'rgba(13,19,32,0.5)' }}>
        <div style={{ display: 'flex', gap: 0, animation: 'ticker 30s linear infinite', whiteSpace: 'nowrap', width: 'max-content' }}>
          <span style={{ fontFamily: "'Space Mono',monospace", fontSize: '11px', color: '#64748b', padding: '0 32px', letterSpacing: '0.1em' }}>
            UNISWAP V3 · {marketingTransactions} TX SCORED &nbsp;·&nbsp; {marketingAlerts} ALERTS FIRED &nbsp;·&nbsp; AAVE · MONITORING ACTIVE &nbsp;·&nbsp; COMPOUND · WATCHING &nbsp;·&nbsp; RISK THRESHOLD: {appSettings.risk_alert_threshold} &nbsp;·&nbsp;
          </span>
          <span style={{ fontFamily: "'Space Mono',monospace", fontSize: '11px', color: '#64748b', padding: '0 32px', letterSpacing: '0.1em' }}>
            UNISWAP V3 · {marketingTransactions} TX SCORED &nbsp;·&nbsp; {marketingAlerts} ALERTS FIRED &nbsp;·&nbsp; AAVE · MONITORING ACTIVE &nbsp;·&nbsp; COMPOUND · WATCHING &nbsp;·&nbsp; RISK THRESHOLD: {appSettings.risk_alert_threshold} &nbsp;·&nbsp;
          </span>
          <span style={{ fontFamily: "'Space Mono',monospace", fontSize: '11px', color: '#64748b', padding: '0 32px', letterSpacing: '0.1em' }}>
            UNISWAP V3 · {marketingTransactions} TX SCORED &nbsp;·&nbsp; {marketingAlerts} ALERTS FIRED &nbsp;·&nbsp; AAVE · MONITORING ACTIVE &nbsp;·&nbsp; COMPOUND · WATCHING &nbsp;·&nbsp; RISK THRESHOLD: {appSettings.risk_alert_threshold} &nbsp;·&nbsp;
          </span>
        </div>
      </div>

      <section className="landing-band two-col">
        <div>
          <h2><span className="problem-number">$17B</span> stolen from DeFi in 2025.</h2>
          <p>Most protocols have zero automated monitoring. By the time you see it on Twitter, it's over.</p>
        </div>
        <div>
          <h2>Your protocol needs someone watching.</h2>
          <p>Euler lost $197M in one transaction. <span className="problem-number">Ronin lost $625M</span> and took days to notice.</p>
        </div>
      </section>

      <section className="landing-band steps">
        <div style={{ fontFamily: "'Space Mono',monospace", fontSize: '10px', letterSpacing: '0.2em', textTransform: 'uppercase', color: '#38bdf8', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '10px', gridColumn: '1 / -1' }}>
          <span style={{ display: 'inline-block', width: '4px', height: '4px', background: '#38bdf8', borderRadius: '50%' }}></span>
          How it works
        </div>
        <article><span>01.</span><h3>Connect</h3><p>Add your contract address. Takes 30 seconds.</p></article>
        <article><span>02.</span><h3>Monitor</h3><p>Talosly watches every transaction 24/7 via AI.</p></article>
        <article><span>03.</span><h3>Alert</h3><p>Risk score above {appSettings.risk_alert_threshold} triggers Telegram in seconds.</p></article>
      </section>

      <div style={{ padding: '72px 48px', textAlign: 'center', borderTop: '1px solid rgba(56,189,248,0.08)' }}>
        <div style={{ display: 'flex', justifyContent: 'center', gap: '80px', flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: '56px', fontWeight: 800, fontFamily: "'Syne',sans-serif", lineHeight: 1 }}>{marketingTransactions}</div>
            <div style={{ fontFamily: "'Space Mono',monospace", fontSize: '11px', color: '#64748b', letterSpacing: '0.15em', textTransform: 'uppercase', marginTop: '8px' }}>Transactions Scored</div>
          </div>
          <div>
            <div style={{ fontSize: '56px', fontWeight: 800, fontFamily: "'Syne',sans-serif", lineHeight: 1 }}>{marketingAlerts}</div>
            <div style={{ fontFamily: "'Space Mono',monospace", fontSize: '11px', color: '#64748b', letterSpacing: '0.15em', textTransform: 'uppercase', marginTop: '8px' }}>Alerts Fired</div>
          </div>
          <div>
            <div style={{ fontSize: '56px', fontWeight: 800, fontFamily: "'Syne',sans-serif", lineHeight: 1 }}>KYA</div>
            <div style={{ fontFamily: "'Space Mono',monospace", fontSize: '11px', color: '#64748b', letterSpacing: '0.15em', textTransform: 'uppercase', marginTop: '8px' }}>Agent Flow</div>
          </div>
          <div>
            <div style={{ fontSize: '56px', fontWeight: 800, fontFamily: "'Syne',sans-serif", color: '#34d399', lineHeight: 1 }}>{appSettings.marketing_alert_latency}</div>
            <div style={{ fontFamily: "'Space Mono',monospace", fontSize: '11px', color: '#64748b', letterSpacing: '0.15em', textTransform: 'uppercase', marginTop: '8px' }}>Alert Latency</div>
          </div>
        </div>
      </div>

      <section className="landing-band quote">
        <div style={{ fontFamily: "'Space Mono',monospace", fontSize: '10px', letterSpacing: '0.2em', textTransform: 'uppercase', color: '#38bdf8', marginBottom: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px' }}>
          <span style={{ display: 'inline-block', width: '4px', height: '4px', background: '#38bdf8', borderRadius: '50%' }}></span>
          Private beta
        </div>
        <p>"Finally, monitoring that doesn't require a $30K/yr security contract."</p>
        <span>— DeFi Founder, private beta</span>
      </section>

      <section className="landing-band apply-section" id="apply">
        <div>
          <div style={{ fontFamily: "'Space Mono',monospace", fontSize: '10px', letterSpacing: '0.2em', textTransform: 'uppercase', color: '#38bdf8', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ display: 'inline-block', width: '4px', height: '4px', background: '#38bdf8', borderRadius: '50%' }}></span>
            Access
          </div>
          <h2>Apply for Beta</h2>
          <p>Free during beta. No credit card.</p>
        </div>
        <form className="beta-form" onSubmit={submit}>
          <input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input placeholder="Email" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <input placeholder="Agent / Project" value={form.project} onChange={(e) => setForm({ ...form, project: e.target.value })} />
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
