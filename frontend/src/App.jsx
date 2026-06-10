import { Navigate, Route, Routes } from 'react-router-dom';
import Admin from './pages/Admin.jsx';
import Agents from './pages/Agents.jsx';
import Landing from './pages/Landing.jsx';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/agents" element={<Agents />} />
      <Route path="/admin" element={<Admin />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
