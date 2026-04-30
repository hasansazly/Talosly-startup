import RiskBadge from './RiskBadge.jsx';

function shorten(value) {
  if (!value) return '—';
  return `${value.slice(0, 10)}...${value.slice(-6)}`;
}

function relativeTime(value) {
  if (!value) return '—';
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(`${value}Z`).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}

export default function TransactionRow({ tx }) {
  return (
    <tr>
      <td className="mono">{shorten(tx.tx_hash)}</td>
      <td className="mono">{shorten(tx.from_address)}</td>
      <td className="mono">{Number(tx.value_eth || 0).toFixed(5)}</td>
      <td><RiskBadge score={tx.risk_score} /></td>
      <td>{relativeTime(tx.fetched_at)}</td>
    </tr>
  );
}
