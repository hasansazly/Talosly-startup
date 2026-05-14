export function getAlertScore(alert) {
  return Number(alert?.risk_score ?? alert?.riskScore ?? 0);
}

export function getAlertProtocol(alert) {
  return alert?.protocol_name || alert?.protocol || 'Unknown protocol';
}

export function getAlertHash(alert) {
  return alert?.tx_hash || alert?.txHash || '—';
}

export function getAlertReason(alert) {
  return alert?.risk_summary || alert?.reason || 'High risk transaction detected';
}

export function getAlertTimestamp(alert) {
  return alert?.created_at || alert?.timestamp || alert?.fetched_at || null;
}

export function getAlertSeverity(score) {
  if (score >= 80) return { label: 'HIGH', tone: 'high' };
  if (score >= 60) return { label: 'MEDIUM', tone: 'medium' };
  return { label: 'LOW', tone: 'low' };
}

export function relativeTime(value, now = Date.now()) {
  if (!value) return '—';
  const parsed = value instanceof Date ? value.getTime() : new Date(value).getTime();
  if (Number.isNaN(parsed)) return '—';
  const seconds = Math.max(0, Math.floor((now - parsed) / 1000));
  if (seconds < 5) return 'just now';
  if (seconds < 60) return `${seconds} sec ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}

export function shorten(value, head = 10, tail = 6) {
  if (!value || value === '—') return '—';
  if (value.length <= head + tail + 3) return value;
  return `${value.slice(0, head)}...${value.slice(-tail)}`;
}

export function getAlertFactors(alert) {
  const source = alert?.risk_factors || alert?.factors || alert?.riskFactors;
  if (Array.isArray(source) && source.length > 0) return source;
  return [getAlertReason(alert)];
}

export function getAlertSummary(alert) {
  return alert?.ai_summary || alert?.aiSummary || alert?.risk_summary || 'Analysis pending';
}

export function getRecommendedAction(score) {
  if (score >= 80) return 'Do not interact. Report to protocol team.';
  if (score >= 60) return 'Review before interacting.';
  return 'Monitor for follow-up activity.';
}

export function buildAlertReport(alert, now = Date.now()) {
  const score = getAlertScore(alert);
  const txHash = getAlertHash(alert);
  const protocol = getAlertProtocol(alert);
  const reason = getAlertReason(alert);
  const timestamp = getAlertTimestamp(alert);
  const etherscan = txHash && txHash !== '—' ? `https://etherscan.io/tx/${txHash}` : '—';

  return {
    protocol,
    txHash,
    riskScore: score,
    reason,
    timestamp,
    etherscan,
    timeLabel: relativeTime(timestamp, now),
  };
}
