import axios from 'axios';

const BASE = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? 'http://localhost:8000' : '');

const api = axios.create({ baseURL: BASE });

function authHeaders() {
  const key = sessionStorage.getItem('talosly_api_key') || localStorage.getItem('talosly_api_key');
  return key ? { Authorization: `Bearer ${key}` } : {};
}

function adminHeaders() {
  const secret = sessionStorage.getItem('talosly_admin_secret');
  return secret ? { 'X-Admin-Secret': secret } : {};
}

async function unwrap(request) {
  try {
    const response = await request;
    return response.data;
  } catch (error) {
    const detail = error.response?.data?.detail || error.message;
    throw new Error(typeof detail === 'string' ? detail : detail.error || 'Talosly request failed');
  }
}

export const getHealth = () => unwrap(api.get('/api/health'));
export const getStats = () => unwrap(api.get('/api/stats'));
export const getDemoTransactions = () => unwrap(api.get('/api/demo/transactions'));
export const applyWaitlist = (payload) => unwrap(api.post('/api/waitlist/apply', payload));
export const getProtocols = () => unwrap(api.get('/api/protocols', { headers: authHeaders() }));
export const addProtocol = (payload) => unwrap(api.post('/api/protocols', payload, { headers: authHeaders() }));
export const deleteProtocol = (id) => unwrap(api.delete(`/api/protocols/${id}`, { headers: authHeaders() }));
export const toggleProtocol = (id) => unwrap(api.patch(`/api/protocols/${id}/toggle`, null, { headers: authHeaders() }));
export const getTransactions = (protocolId, limit = 50) =>
  unwrap(api.get('/api/transactions', { params: { protocol_id: protocolId || undefined, limit }, headers: authHeaders() }));
export const getAlerts = (limit = 100) => unwrap(api.get('/api/alerts', { params: { limit }, headers: authHeaders() }));
export const getAlertStats = () => unwrap(api.get('/api/alerts/stats', { headers: authHeaders() }));
export const getAdminMetrics = () => unwrap(api.get('/api/admin/metrics', { headers: adminHeaders() }));
export const getAdminWaitlist = () => unwrap(api.get('/api/admin/waitlist', { headers: adminHeaders() }));
export const approveWaitlist = (id) => unwrap(api.post(`/api/admin/waitlist/${id}/approve`, null, { headers: adminHeaders() }));
export const rejectWaitlist = (id) => unwrap(api.post(`/api/admin/waitlist/${id}/reject`, null, { headers: adminHeaders() }));
export const getAdminKeys = () => unwrap(api.get('/api/admin/keys', { headers: adminHeaders() }));
export const createAdminKey = (name = 'Dev key') => unwrap(api.post('/api/admin/keys/create', null, { params: { name }, headers: adminHeaders() }));
export const revokeKey = (id) => unwrap(api.delete(`/api/admin/keys/${id}`, { headers: adminHeaders() }));
