import { useEffect } from 'react';
import {
  buildAlertReport,
  getAlertFactors,
  getAlertHash,
  getAlertScore,
  getAlertSeverity,
  getAlertSummary,
  getRecommendedAction,
  shorten,
} from '../utils/alertUi.js';

function copyText(value) {
  if (!navigator.clipboard) return;
  navigator.clipboard.writeText(value);
}

function AddressLine({ label, value }) {
  return (
    <div className="modal-address-row">
      <span>{label}</span>
      <code>{shorten(value)}</code>
      <button type="button" className="tiny-action" onClick={() => copyText(value || '')}>Copy</button>
    </div>
  );
}

function getShapSignals(alert) {
  const source = alert?.shap_top || alert?.layer3?.shap_top || alert?.layer3_result?.shap_top;
  if (!Array.isArray(source)) return [];
  return source
    .filter((signal) => signal && signal.feature)
    .map((signal) => {
      const rawMagnitude = Number(signal.shap ?? signal.value ?? 0);
      return {
        feature: signal.feature,
        value: signal.value,
        magnitude: Math.abs(Number.isFinite(rawMagnitude) ? rawMagnitude : 0),
      };
    })
    .filter((signal) => signal.magnitude > 0)
    .slice(0, 3);
}

function formatSignalValue(value) {
  if (value === undefined || value === null || value === '') return '—';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  if (Math.abs(numeric) >= 100) return numeric.toFixed(0);
  if (Math.abs(numeric) >= 10) return numeric.toFixed(1);
  return numeric.toFixed(3).replace(/\.?0+$/, '');
}

function RiskSignalBreakdown({ signals }) {
  if (!signals.length) return null;

  const maxMagnitude = Math.max(...signals.map((signal) => signal.magnitude), 0.001);

  return (
    <div className="modal-section risk-signal-section">
      <h3>Top Risk Signals</h3>
      <div className="risk-signal-list">
        {signals.map((signal) => (
          <div className="risk-signal-row" key={signal.feature}>
            <div className="risk-signal-meta">
              <span>{signal.feature.replaceAll('_', ' ')}</span>
              <code>{formatSignalValue(signal.value)}</code>
            </div>
            <div className="risk-signal-bar" aria-hidden="true">
              <span style={{ width: `${Math.max((signal.magnitude / maxMagnitude) * 100, 8)}%` }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function AlertDetailModal({ alert, onClose, onCopySummary, onDownloadJson }) {
  useEffect(() => {
    function handleKey(event) {
      if (event.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose]);

  if (!alert) return null;

  const score = getAlertScore(alert);
  const txHash = getAlertHash(alert);
  const severity = getAlertSeverity(score);
  const factors = getAlertFactors(alert);
  const report = buildAlertReport(alert);
  const shapSignals = getShapSignals(alert);

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="alert-modal" role="dialog" aria-modal="true" aria-label="Alert detail" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-heading">
          <div>
            <div className="panel-label">Alert detail</div>
            <h2>{report.protocol}</h2>
          </div>
          <button type="button" className="tiny-action" onClick={onClose}>Close</button>
        </div>

        <div className="modal-hash-line">
          <code>{txHash}</code>
          <button type="button" className="tiny-action" onClick={() => copyText(txHash)}>Copy TX</button>
        </div>

        <div className="modal-score">
          <span className={`severity-pill ${severity.tone}`}>{severity.label} {score}</span>
          <div className="risk-meter"><span style={{ width: `${Math.min(score, 100)}%` }} /></div>
        </div>

        <div className="modal-addresses">
          <AddressLine label="From" value={alert.from_address || alert.from || '—'} />
          <AddressLine label="To" value={alert.to_address || alert.to || '—'} />
        </div>

        <div className="modal-section">
          <h3>Risk Factors</h3>
          <ul>
            {factors.map((factor) => <li key={factor}>{factor}</li>)}
          </ul>
        </div>

        <RiskSignalBreakdown signals={shapSignals} />

        <div className="modal-section">
          <h3>AI Summary</h3>
          <p>{getAlertSummary(alert)}</p>
        </div>

        <div className="modal-section">
          <h3>Recommended Action</h3>
          <p>{getRecommendedAction(score)}</p>
        </div>

        <div className="modal-actions">
          <a className="button-link" href={report.etherscan} target="_blank" rel="noreferrer">Etherscan</a>
          <button type="button" onClick={() => onCopySummary(alert)}>Copy Summary</button>
          <button type="button" onClick={() => onDownloadJson(alert)}>Download JSON</button>
        </div>
      </section>
    </div>
  );
}
