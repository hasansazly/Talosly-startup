import { Navigate, Route, Routes } from 'react-router-dom';
import Admin from './pages/Admin.jsx';
import AgentDetail from './pages/AgentDetail.jsx';
import Agents from './pages/Agents.jsx';
import Dashboard from './pages/Dashboard.jsx';
import Landing from './pages/Landing.jsx';

export default function App() {
  return (
    <Routes>
      <Route path="/"             element={<Landing />} />
      <Route path="/agents"       element={<Agents />} />
      <Route path="/agents/:id"   element={<AgentDetail />} />
      <Route path="/dashboard"    element={<Dashboard />} />
      <Route path="/admin"        element={<Admin />} />
      <Route path="*"             element={<Navigate to="/" replace />} />
    </Routes>
  );
}
