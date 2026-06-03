function formatTime(value) {
  if (!value) return 'pending';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'pending';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export default function AgentTrustChart({ history }) {
  const points = history?.length ? history.slice(-12) : [];

  return (
    <section className="panel agent-chart-panel">
      <div className="panel-heading">
        <div>
          <div className="panel-label">Trust score over time</div>
          <h2>{points.length ? `${points.length} recent observations` : 'No score history yet'}</h2>
        </div>
      </div>
      {points.length ? (
        <div className="agent-trust-chart" aria-label="Agent trust score history">
          {points.map((point, index) => {
            const score = Number(point.trust_score ?? 0);
            return (
              <div className="trust-point" key={`${point.computed_at || 'score'}-${index}`}>
                <div className="trust-bar-track">
                  <span style={{ height: `${Math.max(Math.min(score, 100), 4)}%` }} />
                </div>
                <strong>{score}</strong>
                <small>{formatTime(point.computed_at)}</small>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="empty-alert">Score an action or wait for the KYA worker to populate trust history.</div>
      )}
    </section>
  );
}
