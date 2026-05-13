import { useEffect, useMemo, useState } from 'react';
import Header from '../components/Header.jsx';
import { getHealth, runDemoReplay } from '../api.js';

const EULER_HASH = '0xc310a0affe2169d1f6feec1c63dbc7f7c62a887fa48795d327d4d2da2d6b111d';

function short(value) {
  if (!value) return 'n/a';
  return `${value.slice(0, 10)}...${value.slice(-8)}`;
}

function factorLabel(factor) {
  return factor.toLowerCase().replaceAll('_', ' ');
}

export default function Replay() {
  const [online, setOnline] = useState(false);
  const [lastUpdated, setLastUpdated] = useState('');
  const [txHash, setTxHash] = useState(EULER_HASH);
  const [result, setResult] = useState(null);
  const [activeStage, setActiveStage] = useState(-1);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState('');

  const traceSteps = result?.trace || [];
  const riskScore = result?.score ?? result?.result?.risk_score ?? 0;
  const behavioralScore = result?.behavior_score ?? result?.behavioral_result?.risk_score ?? 0;
  const riskFactors = result?.factors || result?.behavioral_result?.risk_factors || result?.result?.risk_factors || [];
  const isCritical = riskScore >= 70;

  const scoreStyle = useMemo(() => ({
    '--score-degrees': `${Math.min(riskScore, 100) * 3.6}deg`,
  }), [riskScore]);

  useEffect(() => {
    getHealth()
      .then(() => {
        setOnline(true);
        setLastUpdated(new Date().toLocaleTimeString());
      })
      .catch(() => setOnline(false));
  }, []);

  useEffect(() => {
    if (!isRunning || !result) return undefined;
    setActiveStage(-1);
    const steps = result.trace || result.stages || [];
    const timers = steps.map((_, index) => (
      setTimeout(() => setActiveStage(index), 420 + index * 420)
    ));
    const done = setTimeout(() => setIsRunning(false), 420 + steps.length * 420);
    return () => {
      timers.forEach(clearTimeout);
      clearTimeout(done);
    };
  }, [isRunning, result]);

  async function analyze(event) {
    event.preventDefault();
    setError('');
    setResult(null);
    setIsRunning(true);
    try {
      const replay = await runDemoReplay(txHash);
      setResult(replay);
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (nextError) {
      setIsRunning(false);
      setError(nextError.message);
    }
  }

  return (
    <main className="app-shell replay-shell">
      <Header online={online} lastUpdated={lastUpdated} />

      <section className="replay-workspace">
        <div className="replay-main">
          <section className="panel replay-control">
            <div>
              <div className="panel-label">Historical replay</div>
              <h1>Euler Finance attack analysis</h1>
            </div>
            <form className="replay-form" onSubmit={analyze}>
              <input
                aria-label="Transaction hash"
                value={txHash}
                onChange={(event) => setTxHash(event.target.value)}
                spellCheck="false"
              />
              <button type="submit" disabled={isRunning}>{isRunning ? 'Analyzing' : 'Analyze'}</button>
            </form>
            {error && <p className="form-error">{error}</p>}
          </section>

          <section className={`panel alert-reveal ${isCritical ? 'critical' : ''}`}>
            <div className="alert-copy">
              <div className="panel-label">{isCritical ? 'Red alert' : 'Waiting for replay'}</div>
              <h2>{isCritical ? 'Critical exploit path detected' : 'Paste a hash and run analysis'}</h2>
              <p>
                {result
                  ? result.result.risk_summary
                  : 'Talosly will score the transaction and stage a protocol response.'}
              </p>
            </div>
            <div className="score-dial" style={scoreStyle}>
              <strong>{riskScore}</strong>
              <span>/100</span>
            </div>
          </section>

          <section className="replay-grid">
            <div className="panel transaction-panel">
              <div className="panel-label">Transaction</div>
              <dl>
                <div><dt>Hash</dt><dd className="mono">{short(result?.transaction?.tx_hash || txHash)}</dd></div>
                <div><dt>Protocol</dt><dd>{result?.protocol?.name || 'Euler Finance'}</dd></div>
                <div><dt>Value</dt><dd>{result ? `${result.transaction.value_eth} ETH` : '0 ETH'}</dd></div>
                <div><dt>Gas Used</dt><dd>{result?.transaction?.gas_used?.toLocaleString() || '6,211,412'}</dd></div>
              </dl>
              {result?.hash_note && <p className="hash-note">{result.hash_note}</p>}
            </div>

            <div className="panel response-panel">
              <div className="panel-label">S2 response</div>
              <button className={`pause-button ${isCritical ? 'armed' : ''}`} type="button">
                {isCritical ? 'Pause Armed' : 'Pause Standby'}
              </button>
              <p className="mono">{result?.action || 'MONITOR'}</p>
              <p>{result ? `${result.elapsed_ms} ms detection path` : 'Awaiting replay packet'}</p>
            </div>
          </section>
        </div>

        <aside className="replay-side">
          <section className="panel logic-panel">
            <div className="panel-label">AI Brain trace</div>
            <h2>Detection logic</h2>
            <ol className="stage-list">
              {(traceSteps.length ? traceSteps : [
                'Waiting for live RPC transaction',
                'Weighted scorer ready',
                'Behavior-only score pending',
                'Protocol response pending',
              ]).map((stage, index) => (
                <li className={index <= activeStage ? 'active' : ''} key={stage}>
                  <span>{String(index + 1).padStart(2, '0')}</span>
                  {stage}
                </li>
              ))}
            </ol>
          </section>

          <section className="panel factors-panel">
            <div className="panel-label">Risk factors</div>
            <div className="factor-stack">
              {(riskFactors.length ? riskFactors : ['AWAITING_ANALYSIS']).map((factor) => (
                <span key={factor}>{factorLabel(factor)}</span>
              ))}
            </div>
            <div className="behavior-score">
              <span>Behavior-only score</span>
              <strong>{behavioralScore}/100</strong>
            </div>
          </section>

          <section className="panel code-panel">
            <div className="panel-label">Scorer path</div>
            <pre>{`if blacklisted(address):
  score = 98
score += weighted_behavior_points(tx)
if score >= 70:
  trigger("PROTOCOL_PAUSE_READY")`}</pre>
          </section>
        </aside>
      </section>
    </main>
  );
}
