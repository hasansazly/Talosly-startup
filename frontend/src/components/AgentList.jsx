function trustTone(score) {
  if (score >= 80) return 'low';
  if (score >= 55) return 'medium';
  return 'critical';
}

export default function AgentList({ agents, selectedId, onSelect }) {
  return (
    <section className="panel agent-list-panel">
      <div className="panel-heading">
        <div>
          <div className="panel-label">Registered agents</div>
          <h2>Autonomous wallets</h2>
        </div>
      </div>
      <div className="agent-list">
        {agents.map((agent) => (
          <button
            type="button"
            className={`agent-list-item ${selectedId === agent.id ? 'selected' : ''}`}
            key={agent.id}
            onClick={() => onSelect(agent)}
          >
            <span>
              <strong>{agent.name}</strong>
              <code>{agent.wallet?.address || agent.principal_ref}</code>
            </span>
            <span className={`risk-badge ${trustTone(agent.latestScore?.trust_score ?? 0)}`}>
              {agent.latestScore ? `${agent.latestScore.trust_score}` : 'NEW'}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
