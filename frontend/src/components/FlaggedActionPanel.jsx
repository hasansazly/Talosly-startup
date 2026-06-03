import RiskSignalBreakdown from './RiskSignalBreakdown.jsx';

export default function FlaggedActionPanel({ score }) {
  if (!score) {
    return (
      <section className="panel flagged-action-panel">
        <div className="panel-label">Flagged action</div>
        <h2>No flagged action selected</h2>
        <p className="address">High-risk agent actions will show SHAP signal attribution here.</p>
      </section>
    );
  }

  const risk = 100 - Number(score.trust_score || 0);
  return (
    <section className="panel flagged-action-panel">
      <div className="panel-heading">
        <div>
          <div className="panel-label">Flagged action</div>
          <h2>{score.action || score.tx_hash || 'Agent action'}</h2>
        </div>
        <span className={`severity-pill ${risk >= 80 ? 'high' : 'medium'}`}>Risk {risk}</span>
      </div>
      <div className="factor-list">
        {(score.risk_factors || []).map((factor) => <span key={factor}>{factor.replaceAll('_', ' ')}</span>)}
      </div>
      <RiskSignalBreakdown signals={score.shap_top || []} title="SHAP Signal Breakdown" />
    </section>
  );
}
