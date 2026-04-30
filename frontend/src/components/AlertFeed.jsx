import RiskBadge from './RiskBadge.jsx';

export default function AlertFeed({ alerts }) {
  return (
    <section className="alert-strip">
      {alerts.length === 0 ? (
        <div className="empty-alert">No Talosly alerts yet</div>
      ) : (
        alerts.map((alert) => (
          <article className="alert-chip" key={alert.id}>
            <RiskBadge score={alert.risk_score} />
            <span>{alert.risk_summary || 'High risk transaction detected'}</span>
          </article>
        ))
      )}
    </section>
  );
}
