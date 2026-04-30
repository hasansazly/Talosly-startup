import axios from 'axios';

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({ baseURL: BASE });

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
export const getProtocols = () => unwrap(api.get('/api/protocols'));
export const addProtocol = (payload) => unwrap(api.post('/api/protocols', payload));
export const deleteProtocol = (id) => unwrap(api.delete(`/api/protocols/${id}`));
export const toggleProtocol = (id) => unwrap(api.patch(`/api/protocols/${id}/toggle`));
export const getTransactions = (protocolId, limit = 50) =>
  unwrap(api.get('/api/transactions', { params: { protocol_id: protocolId || undefined, limit } }));
export const getAlerts = (limit = 100) => unwrap(api.get('/api/alerts', { params: { limit } }));
export const getAlertStats = () => unwrap(api.get('/api/alerts/stats'));
