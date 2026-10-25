import type { ReactNode } from 'react';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from './auth/AuthContext';
import Layout, { NAV } from './components/Layout';
import { ErrorBox, Loading } from './components/ui';
import { ApiError } from './api/client';
import AdminPage from './pages/Admin';
import CaseDetailPage from './pages/CaseDetail';
import DataFlowPage from './pages/DataFlow';
import EmployeeProfilePage from './pages/EmployeeProfile';
import ExplorerPage from './pages/Explorer';
import HealthPage from './pages/Health';
import InsightsPage from './pages/Insights';
import LearningPage from './pages/Learning';
import LoginPage from './pages/Login';
import OverviewPage from './pages/Overview';
import ReportsPage from './pages/Reports';
import ScenariosPage from './pages/Scenarios';

function Guard({ permissions, children }: { permissions: string[]; children: ReactNode }) {
  const { can } = useAuth();
  return can(...permissions) ? <>{children}</> : <ErrorBox error={new ApiError(403, 'forbidden')} />;
}

function Home() {
  const { can } = useAuth();
  const first = NAV.find((item) => can(...item.permissions));
  return <Navigate to={first?.to ?? '/overview'} replace />;
}

export default function App() {
  const { user, ready } = useAuth();
  if (!ready) return <Loading />;
  if (!user) return <LoginPage />;

  // HashRouter keeps routing working for nginx, the Vite dev server and Electron's app:// protocol alike.
  return (
    <HashRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="overview" element={<Guard permissions={['dashboard.view']}><OverviewPage /></Guard>} />
          <Route path="explorer" element={<Guard permissions={['cases.view']}><ExplorerPage /></Guard>} />
          <Route path="cases/:caseId" element={<Guard permissions={['cases.view']}><CaseDetailPage /></Guard>} />
          <Route path="learning" element={<Guard permissions={['learning.view']}><LearningPage /></Guard>} />
          <Route
            path="learning/:employeeId"
            element={<Guard permissions={['learning.view']}><EmployeeProfilePage /></Guard>}
          />
          <Route path="insights" element={<Guard permissions={['insights.view']}><InsightsPage /></Guard>} />
          <Route path="scenarios" element={<Guard permissions={['simulations.run']}><ScenariosPage /></Guard>} />
          <Route
            path="reports"
            element={<Guard permissions={['reports.view', 'reports.ops']}><ReportsPage /></Guard>}
          />
          <Route path="data-flow" element={<Guard permissions={['dashboard.view']}><DataFlowPage /></Guard>} />
          <Route path="health" element={<Guard permissions={['ops.view']}><HealthPage /></Guard>} />
          <Route path="admin" element={<Guard permissions={['admin.view', 'audit.view']}><AdminPage /></Guard>} />
          <Route path="*" element={<Home />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
