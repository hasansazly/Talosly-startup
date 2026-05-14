import {
  buildAlertReport,
  getAlertReason,
  getAlertScore,
  getAlertSeverity,
  relativeTime,
} from '../utils/alertUi.js';

export function copyAlertSummary(alert) {
  const report = buildAlertReport(alert);
  const text = [
    `🚨 ${report.protocol} | Risk: ${report.riskScore} | ${report.reason} | ${report.timeLabel}`,
    `TX: ${report.txHash}`,
    `Etherscan: ${report.etherscan}`,
  ].join('\n');
  if (navigator.clipboard) navigator.clipboard.writeText(text);
}

export function downloadAlertJson(alert) {
  const report = buildAlertReport(alert);
  const payload = {
    protocol: report.protocol,
    txHash: report.txHash,
    riskScore: report.riskScore,
    reason: report.reason,
    timestamp: report.timestamp,
    etherscan: report.etherscan,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `talosly-alert-${String(report.txHash).replace(/[^a-zA-Z0-9]/g, '').slice(0, 18) || 'report'}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export default function AlertFeed({ alerts, onSelect, now }) {
  return (
    <section className="panel alert-panel">
      <div className="panel-heading">
        <div>
          <div className="panel-label">Alert center</div>
          <h2>Global high-risk alerts</h2>
        </div>
      </div>
      {alerts.length === 0 ? (
        <div className="empty-alert">No high-risk alerts detected across monitored protocols.</div>
      ) : (
        <div className="alert-list">
          {alerts.map((alert) => {
            const report = buildAlertReport(alert, now);
            const score = getAlertScore(alert);
            const severity = getAlertSeverity(score);
            const reason = getAlertReason(alert);
            return (
              <article className={`alert-card ${severity.tone}`} key={alert.id || alert.txHash || alert.tx_hash} onClick={() => onSelect(alert)}>
                <div className="alert-line">
                  <strong>{report.protocol}</strong>
                  <span className={`severity-pill ${severity.tone}`}>{severity.label} {score}</span>
                  <span>{reason}</span>
                  <span>{relativeTime(report.timestamp, now)}</span>
                  {alert.demo && <span className="demo-badge">DEMO</span>}
                </div>
                <div className="alert-actions" onClick={(event) => event.stopPropagation()}>
                  <button type="button" className="tiny-action" onClick={() => copyAlertSummary(alert)}>Copy Summary</button>
                  <button type="button" className="tiny-action" onClick={() => downloadAlertJson(alert)}>Download JSON</button>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
