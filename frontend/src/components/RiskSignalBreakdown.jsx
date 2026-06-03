function formatSignalValue(value) {
  if (value === undefined || value === null || value === '') return '—';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  if (Math.abs(numeric) >= 100) return numeric.toFixed(0);
  if (Math.abs(numeric) >= 10) return numeric.toFixed(1);
  return numeric.toFixed(3).replace(/\.?0+$/, '');
}

export function getShapSignals(source) {
  const signals = source?.shap_top || source?.layer3?.shap_top || source?.layer3_result?.shap_top || source;
  if (!Array.isArray(signals)) return [];
  return signals
    .filter((signal) => signal && signal.feature)
    .map((signal) => {
      const rawMagnitude = Number(signal.shap ?? signal.magnitude ?? signal.value ?? 0);
      return {
        feature: signal.feature,
        value: signal.value,
        magnitude: Math.abs(Number.isFinite(rawMagnitude) ? rawMagnitude : 0),
      };
    })
    .filter((signal) => signal.magnitude > 0)
    .slice(0, 3);
}

export default function RiskSignalBreakdown({ signals, title = 'Top Risk Signals' }) {
  const normalizedSignals = getShapSignals(signals);
  if (!normalizedSignals.length) return null;

  const maxMagnitude = Math.max(...normalizedSignals.map((signal) => signal.magnitude), 0.001);

  return (
    <div className="modal-section risk-signal-section">
      <h3>{title}</h3>
      <div className="risk-signal-list">
        {normalizedSignals.map((signal) => (
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
