import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { applyWaitlist, getPublicSettings, getStats } from '../api.js';
import RiskBadge from '../components/RiskBadge.jsx';

function short(value) {
  return value ? `${value.slice(0, 10)}…${value.slice(-6)}` : '—';
}

const SAMPLE_ACTIONS = [
  { id: 1, action: 'agent://treasury/rebalance',      value: 0.5,   trust: 94 },
  { id: 2, action: 'agent://ops/new-counterparty',    value: 142.3, trust: 11 },
  { id: 3, action: 'agent://market-maker/quote',      value: 0.01,  trust: 88 },
];

function TrustPill({ score }) {
  const tone = score >= 80 ? 'low' : score >= 55 ? 'medium' : 'critical';
  return <span className={`risk-badge ${tone}`}>{score}</span>;
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
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    getStats().then(setStats).catch(() => {});
    getPublicSettings().then(setAppSettings).catch(() => {});
  }, []);

  async function submit(event) {
    event.preventDefault();
    setMessage('');
    setSubmitting(true);
    try {
      const result = await applyWaitlist(form);
      setMessage(result.message);
      setForm({ name: '', email: '', project: '', twitter: '', goal: '' });
    } catch (error) {
      setMessage(error.message || "You're already on the list. We'll be in touch.");
    } finally {
      setSubmitting(false);
    }
  }

  const mktTx     = Number(appSettings.marketing_transactions_scored || 0).toLocaleString();
  const mktAlerts = Number(appSettings.marketing_alerts_fired || 0).toLocaleString();
  const threshold = appSettings.risk_alert_threshold;

  return (
    <main className="landing">

      {/* ── HERO ─────────────────────────────────────────────────── */}
      <section className="landing-hero">
        <nav className="landing-nav">
          <span className="wordmark">Talosly</span>
          <div>
            <Link to="/agents" className="nav-link">Open Dashboard</Link>
            <a href="#apply" className="button-link">Request Access</a>
          </div>
        </nav>

        <div className="hero-grid">
          <div>
            <div className="hero-eyebrow">
              <span className="dot" />
              Beta · Private Access
            </div>
            <h1>The integrity layer for <em>agent-initiated</em> financial actions.</h1>
            <p className="hero-copy">
              AI agents now move real money. Platforms that deploy them inherit liability
              they cannot see, reconstruct, or prove. Talosly is the agent guardian:
              behavioral baseline, change-point detection, and signed evidence for every decision.
            </p>
            <div className="hero-actions">
              <a href="#apply" className="button-link">Request Access</a>
              <Link to="/agents" className="nav-link btn-ghost">Open Agent Dashboard →</Link>
            </div>
            <p className="stat-line">
              {stats.transactions_scored
                ? `${stats.transactions_scored.toLocaleString()} actions scored · ${stats.alerts_fired.toLocaleString()} alerts fired`
                : 'Monitoring active'}
            </p>
          </div>

          <div className="terminal-panel">
            <div className="terminal-titlebar">
              <div className="terminal-traffic" aria-hidden="true">
                <span style={{ background: 'rgba(239,68,68,0.45)' }} />
                <span style={{ background: 'rgba(245,158,11,0.45)' }} />
                <span style={{ background: 'rgba(34,197,94,0.45)' }} />
              </div>
              <span className="terminal-title">talosly://live-feed</span>
            </div>
            <div className="feed-header">Agent action · Value · Trust score</div>
            {SAMPLE_ACTIONS.map((row) => (
              <div className="feed-row" key={row.id}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{short(row.action)}</span>
                <span>{row.value.toFixed(3)} ETH</span>
                <TrustPill score={row.trust} />
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── TICKER ───────────────────────────────────────────────── */}
      <div className="landing-ticker">
        <div className="ticker-inner">
          {[0, 1, 2].map((i) => (
            <span key={i}>
              AGENT GUARDIAN ACTIVE &nbsp;·&nbsp;
              {mktTx} ACTIONS SCORED &nbsp;·&nbsp;
              {mktAlerts} ALERTS FIRED &nbsp;·&nbsp;
              ALERT LATENCY {appSettings.marketing_alert_latency} &nbsp;·&nbsp;
              SHADOW MODE — NEVER IN THE MONEY PATH &nbsp;·&nbsp;
              SIGNED RECEIPTS EMITTED FOR EVERY DECISION &nbsp;·&nbsp;
            </span>
          ))}
        </div>
      </div>

      {/* ── PROBLEM ──────────────────────────────────────────────── */}
      <section className="landing-band">
        <div className="band-eyebrow"><span>The Problem</span></div>
        <div className="two-col" style={{ alignItems: 'start' }}>
          <div>
            <h2>Agents move real money. Platforms inherit the liability.</h2>
            <p>
              An agent-wallet executes a <span className="problem-number">$2M</span> rebalance.
              The counterparty was substituted mid-session by a prompt injection.
              The platform has no record of intent, no baseline to compare against,
              and no evidence chain. Who bears the liability?
            </p>
            <p style={{ marginTop: 16 }}>
              Prompt injection, session hijacking, and behavioral drift are not
              theoretical. They are the operational signature of agents in the wild.
              Without a guardian, your platform carries risk it cannot see or prove.
            </p>
          </div>
          <div>
            <h2>What changes when you can prove every decision.</h2>
            <p>
              Every agent action Talosly observes produces a cryptographically signed
              evidence record: the decision, the signals that fired, the behavioral
              deviation from baseline — Ed25519 signed, SHA-256 hash-chained, append-only.
            </p>
            <p style={{ marginTop: 16 }}>
              You can show any auditor, regulator, or counterparty exactly what the agent
              decided, why it decided it, and that the record has not been altered.
              That is the liability answer.
            </p>
          </div>
        </div>
      </section>

      {/* ── HOW IT WORKS ─────────────────────────────────────────── */}
      <section className="landing-band">
        <div className="band-eyebrow"><span>How It Works</span></div>
        <h2 style={{ marginBottom: 32 }}>Four layers. One guardian.</h2>
        <div className="step-diagram">
          <div className="step-card">
            <span className="step-number">01 · Observe</span>
            <h3>Every action ingested</h3>
            <p>
              Agent actions stream in over the API. Talosly records the full action
              payload — wallet, counterparty, value, selector, context — before scoring begins.
            </p>
          </div>
          <div className="step-card">
            <span className="step-number">02 · Baseline</span>
            <h3>Behavioral profile built</h3>
            <p>
              A per-agent behavioral baseline is maintained. Mahalanobis distance,
              change-point detection, and conformal prediction signals measure deviation
              from each agent's own history.
            </p>
          </div>
          <div className="step-card">
            <span className="step-number">03 · Detect</span>
            <h3>Trust score computed</h3>
            <p>
              A trust score 0–100 is computed for every action. SHAP attribution
              surfaces which signals drove the decision. Mid-session behavioral breaks —
              the signature of prompt injection — trigger immediate alerts.
            </p>
          </div>
          <div className="step-card">
            <span className="step-number">04 · Evidence</span>
            <h3>Signed receipt emitted</h3>
            <p>
              An Ed25519-signed, SHA-256 hash-chained receipt is written to an
              append-only store for every scored action. The decision is explainable
              and verifiable, always.
            </p>
          </div>
        </div>
      </section>

      {/* ── SHADOW MODE ──────────────────────────────────────────── */}
      <section className="landing-band">
        <div className="band-eyebrow"><span>Architecture</span></div>
        <div className="shadow-mode-card">
          <div className="shadow-icon">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--text-muted)' }}>
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
          </div>
          <div>
            <div className="band-eyebrow" style={{ marginBottom: 12 }}><span>Shadow Mode</span></div>
            <h2 style={{ fontSize: 'clamp(22px, 2.5vw, 32px)', marginBottom: 12 }}>
              Talosly never touches the money path.
            </h2>
            <p style={{ color: 'var(--text-secondary)', lineHeight: 1.7, fontSize: 16 }}>
              Talosly operates in shadow mode: observe, score, and alert — but never
              intercept, block, or route. Your agent execution path is unchanged.
              Talosly sits alongside it, not inside it. The risk of adding a monitoring
              layer to a transaction path is zero, because we are not in the path.
            </p>
            <p style={{ color: 'var(--text-secondary)', lineHeight: 1.7, fontSize: 16, marginTop: 14 }}>
              This is a deliberate architectural choice. A monitor that can block is a
              monitor that can fail. We emit evidence. You decide what to do with it.
            </p>
          </div>
        </div>
      </section>

      {/* ── PRODUCT SURFACE ──────────────────────────────────────── */}
      <section className="landing-band">
        <div className="band-eyebrow"><span>What You Get</span></div>
        <h2 style={{ marginBottom: 32 }}>The full guardian surface.</h2>
        <div className="feature-grid">
          <div className="feature-card">
            <div className="feature-icon">Trust Score</div>
            <h3>Per-agent trust score, 0–100</h3>
            <p>
              Every agent action receives a behavioral trust score computed against that
              agent's own baseline. Not a generic risk score — a signal specific to how
              this agent normally behaves.
            </p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">Behavioral Baseline</div>
            <h3>Change-point detection</h3>
            <p>
              Mahalanobis distance, CUSUM-style change-point signals, and conformal
              prediction intervals detect mid-session behavioral breaks — the statistical
              signature of prompt injection or session manipulation.
            </p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">Explainable Evidence</div>
            <h3>SHAP attribution for every decision</h3>
            <p>
              Each scored action includes a SHAP signal breakdown: which features drove
              the trust score up or down, with normalized attribution weights.
              The decision is never a black box.
            </p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">Signed Receipts</div>
            <h3>Ed25519-signed, hash-chained records</h3>
            <p>
              Every decision produces a receipt: Ed25519-signed, SHA-256 hash-chained
              to the prior receipt, written to an append-only store.
              Tamper-evident and independently verifiable.
            </p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">Alerts</div>
            <h3>Threshold alerts via Telegram</h3>
            <p>
              When trust score falls below your configured threshold, Talosly fires an
              alert — with the full signal breakdown and recommended action — in under 3 seconds.
            </p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">Protocol Monitoring</div>
            <h3>DeFi transaction scoring</h3>
            <p>
              For teams running protocol-level monitoring alongside agent monitoring:
              Layer 3 signal analysis on raw DeFi transactions, with the same
              explainable breakdown.
            </p>
          </div>
        </div>
      </section>

      {/* ── EVIDENCE CHAIN EXPLAINER ──────────────────────────────── */}
      <section className="landing-band">
        <div className="band-eyebrow"><span>Evidence Layer</span></div>
        <div className="two-col">
          <div>
            <h2>Every decision is provable.</h2>
            <p>
              Talosly emits a cryptographically signed receipt for every scored action.
              Each receipt is SHA-256 hashed, signed with Ed25519, and chained to the
              previous receipt via <code style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>previous_hash</code>.
              The store is append-only: PostgreSQL triggers reject any UPDATE or DELETE.
            </p>
            <p style={{ marginTop: 16 }}>
              You can fetch and verify any receipt independently. The verification
              endpoint checks both hash integrity and Ed25519 signature validity.
              This is the evidence record that survives a dispute.
            </p>
          </div>
          <div className="evidence-panel">
            <div className="panel-label">Receipt chain sample</div>
            <div className="evidence-chain">
              <div className="chain-link">
                <span className="dot" />
                kya-receipt/v1 · #001
              </div>
              <span className="chain-connector">→</span>
              <div className="chain-link">
                <span className="dot" />
                #002 · prev_hash verified
              </div>
              <span className="chain-connector">→</span>
              <div className="chain-link">
                <span className="dot" />
                #003 · Ed25519 ✓
              </div>
            </div>
            <div style={{ display: 'grid', gap: 8, marginTop: 8 }}>
              {[
                ['version',   'kya-action-receipt/v1'],
                ['signature', 'Ed25519 · base64-encoded'],
                ['hash_valid','SHA-256 canonical JSON'],
                ['store',     'append-only · pg triggers'],
              ].map(([k, v]) => (
                <div key={k} style={{
                  display: 'grid', gridTemplateColumns: '110px 1fr', gap: 10,
                  borderBottom: '1px solid var(--border)', paddingBottom: 8,
                  fontFamily: 'var(--font-mono)', fontSize: 12,
                }}>
                  <span style={{ color: 'var(--text-muted)', letterSpacing: '0.06em', textTransform: 'uppercase', fontSize: 11 }}>{k}</span>
                  <span style={{ color: 'var(--text-secondary)' }}>{v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── WHO IT'S FOR ──────────────────────────────────────────── */}
      <section className="landing-band">
        <div className="band-eyebrow"><span>Audience</span></div>
        <h2 style={{ marginBottom: 28 }}>Built for teams deploying agents with financial authority.</h2>
        <div className="feature-grid">
          <div className="feature-card">
            <h3>Agent-wallet platforms</h3>
            <p>
              Your agent holds keys and executes trades. You need to know when its
              behavior has shifted — before a loss, not after.
            </p>
          </div>
          <div className="feature-card">
            <h3>Agent-commerce infrastructure</h3>
            <p>
              Autonomous purchasing and payment agents need an audit trail that satisfies
              finance, legal, and counterparty due diligence simultaneously.
            </p>
          </div>
          <div className="feature-card">
            <h3>AI trading agents</h3>
            <p>
              Strategy drift, prompt injection, and session manipulation are live risks.
              Talosly detects behavioral breaks at the statistical layer — not the
              outcome layer, where it's already too late.
            </p>
          </div>
          <div className="feature-card">
            <h3>Protocol operators</h3>
            <p>
              Teams running DeFi protocols who also manage or interact with
              agent-controlled wallets need both layers of monitoring under one system.
            </p>
          </div>
        </div>
      </section>

      {/* ── WAITLIST ──────────────────────────────────────────────── */}
      <section className="landing-band apply-section" id="apply">
        <div>
          <div className="band-eyebrow"><span>Access</span></div>
          <h2>Request beta access.</h2>
          <p style={{ color: 'var(--text-secondary)', marginTop: 12, lineHeight: 1.7 }}>
            Talosly is in private beta. No credit card. No commitment.
            We review every application and reach out directly.
          </p>
          <p style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 20, lineHeight: 1.6 }}>
            We're particularly interested in teams deploying agents with custody
            over real assets — wallets, trading positions, or payment authority.
          </p>
        </div>
        <form className="beta-form" onSubmit={submit}>
          <input
            placeholder="Name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <input
            placeholder="Work email"
            type="email"
            required
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
          <input
            placeholder="Company / project"
            value={form.project}
            onChange={(e) => setForm({ ...form, project: e.target.value })}
          />
          <input
            placeholder="Twitter / X handle"
            value={form.twitter}
            onChange={(e) => setForm({ ...form, twitter: e.target.value })}
          />
          <textarea
            placeholder="Describe the agent or system you're deploying — what financial authority does it have?"
            value={form.goal}
            onChange={(e) => setForm({ ...form, goal: e.target.value })}
          />
          <button type="submit" disabled={submitting}>
            {submitting ? 'Submitting…' : 'Submit Application'}
          </button>
          {message && <div className="form-message">{message}</div>}
        </form>
      </section>

      <footer className="landing-footer">
        <span className="wordmark">Talosly</span>
        <span>The integrity and evidence layer for agent-initiated financial actions.</span>
        <span style={{ color: 'var(--text-muted)' }}>© 2026 Talosly</span>
      </footer>
    </main>
  );
}
