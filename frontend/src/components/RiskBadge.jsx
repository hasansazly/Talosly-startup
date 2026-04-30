export default function RiskBadge({ score }) {
  let label = 'PENDING';
  let tone = 'pending';
  if (score !== null && score !== undefined) {
    if (score <= 30) {
      label = 'LOW';
      tone = 'low';
    } else if (score <= 60) {
      label = 'MEDIUM';
      tone = 'medium';
    } else if (score <= 70) {
      label = 'ELEVATED';
      tone = 'elevated';
    } else {
      label = 'HIGH';
      tone = 'critical';
    }
  }
  return <span className={`risk-badge ${tone}`}>[{label} {score ?? '--'}]</span>;
}
