import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Sidebar } from './components/Sidebar';
import { TopologyPage } from './pages/TopologyPage';
import { MetricsPage } from './pages/MetricsPage';
import { FlowsPage } from './pages/FlowsPage';
import { TrainingPage } from './pages/TrainingPage';
import { ProgressPage } from './pages/ProgressPage';
import { EvaluationPage } from './pages/EvaluationPage';
import { ReportsPage } from './pages/ReportsPage';
import { CopilotPage } from './pages/CopilotPage';

export function App() {
  return (
    <BrowserRouter>
      <div className="flex h-screen overflow-hidden bg-slate-950">
        <Sidebar />
        <main className="flex-1 overflow-y-auto p-6">
          <Routes>
            <Route path="/" element={<TopologyPage />} />
            <Route path="/metrics" element={<MetricsPage />} />
            <Route path="/flows" element={<FlowsPage />} />
            <Route path="/training" element={<TrainingPage />} />
            <Route path="/progress" element={<ProgressPage />} />
            <Route path="/evaluation" element={<EvaluationPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/copilot" element={<CopilotPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
