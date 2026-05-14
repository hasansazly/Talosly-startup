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
