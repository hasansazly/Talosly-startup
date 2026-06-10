import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getAgentReceipts, getAgentScore, getAgents, getHealth, sendAgentTestAlert, verifyReceipt } from '../api.js';
import Nav from '../components/Nav.jsx';
import RiskSignalBreakdown from '../components/RiskSignalBreakdown.jsx';

function fmt(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch { return iso; }
}

function short(s, head = 8, tail = 6) {
  if (!s) return '—';
  if (s.length <= head + tail + 3) return s;
  return `${s.slice(0, head)}…${s.slice(-tail)}`;
}

function trustTone(score) {
  if (score == null) return 'pending';
  if (score >= 80) return 'low';
  if (score >= 55) return 'medium';
  return 'critical';
}

function trustClass(score) {
  if (score == null) return '';
  if (score >= 80) return 'score-high';
  if (score >= 55) return 'score-medium';
  return 'score-low';
}

function trustColor(score) {
  if (score >= 80) return 'var(--success)';
  if (score >= 55) return 'var(--warning)';
  return 'var(--danger)';
}

function GaugeBar({ score }) {
  const pct = Math.min(100, Math.max(0, score ?? 0));
  return (
    <div className="trust-gauge">
      <span style={{ width: `${pct}%`, background: trustColor(score) }} />
    </div>
  );
}

function VerifyPanel({ receipt }) {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  async function verify() {
    setLoading(true);
    setResult(null);
    try {
      const data = await verifyReceipt(receipt.id);
      setResult(data);
    } catch (err) {
      setResult({ error: err.message });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
        <h3 style={{ fontSize: 15, margin: 0 }}>Receipt verification</h3>
        <button onClick={verify} disabled={loading} style={{ fontSize: 12 }}>
          {loading ? 'Verifying…' : 'Verify receipt'}
        </button>
      </div>
      {result && !result.error && (
        <div className={`verify-result ${result.valid ? 'valid' : 'invalid'}`}>
          <span>{result.valid ? '✓' : '✗'}</span>
          <span>
            Hash: {result.hash_valid ? 'valid' : 'MISMATCH'} ·
            Signature: {result.signature_valid ? 'valid' : 'INVALID'} ·
            Receipt: {result.valid ? 'integrity confirmed' : 'TAMPERED'}
          </span>
        </div>
      )}
      {result?.error && (
        <div className="verify-result invalid">
          <span>✗</span>
          <span>{result.error}</span>
        </div>
      )}
    </div>
  );
}

export default function AgentDetail() {
  const { id } = useParams();
  const agentId = Number(id);

  const [online, setOnline] = useState(false);
  const [lastUpdated, setLastUpdated] = useState('');
  const [agent, setAgent] = useState(null);
  const [score, setScore] = useState(null);
  const [receipts, setReceipts] = useState([]);
  const [selectedReceipt, setSelectedReceipt] = useState(null);
  const [message, setMessage] = useState('');
  const [loadingScore, setLoadingScore] = useState(false);
  const [loadingReceipts, setLoadingReceipts] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    getHealth()
      .then(() => { setOnline(true); setLastUpdated(new Date().toLocaleTimeString()); })
      .catch(() => setOnline(false));
  }, []);

  useEffect(() => {
    if (!agentId) return;
    getAgents()
      .then((list) => {
        const found = list.find((a) => a.id === agentId);
        setAgent(found || null);
      })
      .catch((e) => setError(e.message));
  }, [agentId]);

  useEffect(() => {
    if (!agentId) return;
    setLoadingScore(true);
    getAgentScore(agentId)
      .then(setScore)
      .catch(() => {})
      .finally(() => setLoadingScore(false));

    setLoadingReceipts(true);
    getAgentReceipts(agentId, 50)
      .then((data) => { setReceipts(data); if (data.length > 0) setSelectedReceipt(data[0]); })
      .catch(() => {})
      .finally(() => setLoadingReceipts(false));
  }, [agentId]);

  async function refreshScore() {
    setLoadingScore(true);
    setMessage('');
    try {
      const latest = await getAgentScore(agentId);
      setScore(latest);
      setMessage('Score refreshed.');
    } catch (e) {
      setMessage(e.message);
    } finally {
      setLoadingScore(false);
    }
  }

  async function testAlert() {
    setMessage('');
    try {
      const r = await sendAgentTestAlert(agentId);
      setMessage(r.message);
    } catch (e) {
      setMessage(e.message);
    }
  }

  const trustScore = score?.trust_score ?? null;
  const riskScore  = trustScore != null ? 100 - Number(trustScore) : null;

  return (
    <main className="app-shell" style={{ gridTemplateRows: 'auto 1fr' }}>
      <Nav online={online} lastUpdated={lastUpdated} />

      <div style={{ display: 'grid', gap: 16 }}>
        {/* breadcrumb */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-muted)', fontSize: 13 }}>
          <Link to="/agents" style={{ color: 'var(--text-muted)', textDecoration: 'none' }}>
            ← All Agents
          </Link>
          {agent && (
            <>
              <span>/</span>
              <span style={{ color: 'var(--text-primary)' }}>{agent.name}</span>
            </>
          )}
        </div>

        {error && <div className="form-error">{error}</div>}

        {/* agent header */}
        {agent ? (
          <div className="panel" style={{ display: 'grid', gap: 20 }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
              <div>
                <div className="panel-label">Agent Guardian</div>
                <h1 style={{ fontSize: 'clamp(24px, 3vw, 40px)', marginTop: 6 }}>{agent.name}</h1>
                <div className="address" style={{ marginTop: 8 }}>
                  {agent.wallet?.address || agent.principal_ref}
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
                  <span className={`risk-badge ${agent.monitoring_status === 'active' ? 'low' : 'pending'}`}>
                    {agent.monitoring_status || 'pending'}
                  </span>
                  <span className="risk-badge pending">{agent.chain || 'ethereum'}</span>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button onClick={refreshScore} disabled={loadingScore} className="btn-ghost">
                  {loadingScore ? 'Loading…' : 'Refresh score'}
                </button>
                <button onClick={testAlert}>Send test alert</button>
              </div>
            </div>

            {/* trust score display */}
            {trustScore != null ? (
              <div style={{ borderTop: '1px solid var(--border)', paddingTop: 20 }}>
                <div className="panel-label" style={{ marginBottom: 12 }}>Current trust score</div>
                <div className="trust-score-hero">
                  <div className={`trust-score-numeral ${trustClass(trustScore)}`}>
                    {trustScore}
                  </div>
                  <div style={{ display: 'grid', gap: 6, flex: 1, maxWidth: 200 }}>
                    <GaugeBar score={trustScore} />
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                      risk {riskScore} · {riskScore >= 70 ? 'elevated' : riskScore >= 40 ? 'moderate' : 'normal'}
                    </div>
                  </div>
                  {score?.decision && (
                    <span className={`severity-pill ${riskScore >= 70 ? 'high' : riskScore >= 40 ? 'medium' : 'low'}`}>
                      {score.decision}
                    </span>
                  )}
                </div>
                {score?.computed_at && (
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginTop: 10 }}>
                    Computed {fmt(score.computed_at)}
                  </div>
                )}
              </div>
            ) : (
              <div style={{ borderTop: '1px solid var(--border)', paddingTop: 16 }}>
                <div className="panel-label">Trust score</div>
                <p style={{ color: 'var(--text-muted)', fontSize: 14, marginTop: 6 }}>
                  {loadingScore ? 'Loading score…' : 'No score yet. Score an action to compute the behavioral baseline.'}
                </p>
              </div>
            )}

            {/* risk factors + SHAP breakdown */}
            {score && (score.risk_factors?.length > 0 || score.shap_top?.length > 0) && (
              <div style={{ borderTop: '1px solid var(--border)', paddingTop: 16, display: 'grid', gap: 16 }}>
                {score.risk_factors?.length > 0 && (
                  <div>
                    <div className="panel-label" style={{ marginBottom: 10 }}>Risk factors</div>
                    <div className="factor-list">
                      {score.risk_factors.map((f) => (
                        <span key={f}>{f.replaceAll('_', ' ')}</span>
                      ))}
                    </div>
                  </div>
                )}
                {score.shap_top?.length > 0 && (
                  <RiskSignalBreakdown signals={score.shap_top} title="SHAP Signal Attribution" />
                )}
                {score.decision_detail && (
                  <div>
                    <div className="panel-label" style={{ marginBottom: 6 }}>Decision detail</div>
                    <p style={{ color: 'var(--text-secondary)', fontSize: 14, lineHeight: 1.6 }}>
                      {score.decision_detail}
                    </p>
                  </div>
                )}
              </div>
            )}

            {message && <div className="form-message">{message}</div>}
          </div>
        ) : (
          <div className="panel">
            <p style={{ color: 'var(--text-muted)' }}>
              {error ? error : `Agent ${agentId} not found.`}
            </p>
          </div>
        )}

        {/* receipts section */}
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 380px) minmax(0, 1fr)', gap: 16 }}>
          <div className="panel" style={{ alignContent: 'start', display: 'grid', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <div className="panel-label">Evidence layer</div>
                <h3 style={{ fontSize: 16, marginTop: 4 }}>Signed receipts</h3>
              </div>
              <span className="evidence-badge">Ed25519 · SHA-256</span>
            </div>
            {loadingReceipts && (
              <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>Loading receipts…</p>
            )}
            {!loadingReceipts && receipts.length === 0 && (
              <div className="empty-alert">
                <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>
                  No receipts yet. Each scored action produces a signed receipt.
                </p>
              </div>
            )}
            <div className="receipt-list">
              {receipts.map((r) => (
                <div
                  key={r.id}
                  className={`receipt-row${selectedReceipt?.id === r.id ? ' verified' : ''}`}
                  onClick={() => setSelectedReceipt(r)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === 'Enter' && setSelectedReceipt(r)}
                >
                  <span className="receipt-id">{short(r.id, 12, 8)}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
                    {fmt(r.created_at)}
                  </span>
                  <span className={`risk-badge ${trustTone(r.decision?.trust_score)}`}>
                    {r.decision?.trust_score ?? '—'}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="panel" style={{ alignContent: 'start', display: 'grid', gap: 16 }}>
            {selectedReceipt ? (
              <>
                <div>
                  <div className="panel-label">Receipt detail</div>
                  <h3 style={{ fontSize: 15, marginTop: 4 }}>
                    {short(selectedReceipt.id, 16, 8)}
                  </h3>
                </div>
                <div className="receipt-detail">
                  {[
                    ['Receipt ID',     selectedReceipt.id],
                    ['Version',        selectedReceipt.version],
                    ['Agent ID',       selectedReceipt.agent_id],
                    ['Created',        fmt(selectedReceipt.created_at)],
                    ['Receipt hash',   selectedReceipt.receipt_hash],
                    ['Previous hash',  selectedReceipt.previous_hash || '(first in chain)'],
                    ['Public key',     selectedReceipt.public_key],
                    ['Signature',      selectedReceipt.signature],
                  ].map(([label, value]) => (
                    <div className="field-row" key={label}>
                      <span className="field-label">{label}</span>
                      <span className="field-value">{String(value ?? '—')}</span>
                    </div>
                  ))}
                  {selectedReceipt.decision && (
                    <div className="field-row">
                      <span className="field-label">Trust score</span>
                      <span className={`trust-score-numeral ${trustClass(selectedReceipt.decision.trust_score)}`}
                        style={{ fontSize: 28, lineHeight: 1 }}>
                        {selectedReceipt.decision.trust_score ?? '—'}
                      </span>
                    </div>
                  )}
                </div>
                <VerifyPanel receipt={selectedReceipt} />
              </>
            ) : (
              <div className="empty-alert">
                <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>
                  Select a receipt to inspect and verify it.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
