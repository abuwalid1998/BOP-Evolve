import type { ReactNode } from 'react';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from './auth/AuthContext';
import Layout, { NAV } from './components/Layout';
import { ErrorBox, Loading } from './components/ui';
import { ApiError } from './api/client';
import AdminPage from './pages/Admin';
import CaseDetailPage from './pages/CaseDetail';
import ConfigPage from './pages/Config';
import HowItWorksPage from './pages/HowItWorks';
import EmployeeProfilePage from './pages/EmployeeProfile';
import ExplorerPage from './pages/Explorer';
import HealthPage from './pages/Health';
import InsightsPage from './pages/Insights';
import LearningPage from './pages/Learning';
import LoginPage from './pages/Login';
import OverviewPage from './pages/Overview';
import EmployeeReportPage from './pages/EmployeeReport';
import ReportsPage from './pages/Reports';
import RulesPage from './pages/Rules';
import ScenariosPage from './pages/Scenarios';
import OnboardingPage from './pages/Onboarding';
import WelcomePage from './pages/Welcome';
import WorkforcePage from './pages/Workforce';
import WorkplacePage, { WorkplaceEmployeePage } from './pages/Workplace';

function Guard({ permissions, children }: { permissions: string[]; children: ReactNode }) {
  const { can } = useAuth();
  return can(...permissions) ? <>{children}</> : <ErrorBox error={new ApiError(403, 'forbidden')} />;
}

function Home() {
  const { can } = useAuth();
  const first = NAV.find((item) => item.permissions.length > 0 && can(...item.permissions));
  return <Navigate to={first?.to ?? '/welcome'} replace />;
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
          <Route path="workforce" element={<Guard permissions={['workforce.view']}><WorkforcePage /></Guard>} />
          <Route
            path="workforce/:employeeId"
            element={<Guard permissions={['workforce.view']}><EmployeeReportPage /></Guard>}
          />
          <Route path="workplace" element={<Guard permissions={['workplace.view']}><WorkplacePage /></Guard>} />
          <Route
            path="workplace/employees/:employeeId"
            element={<Guard permissions={['workplace.view']}><WorkplaceEmployeePage /></Guard>}
          />
          <Route path="onboarding" element={<Guard permissions={['onboarding.manage']}><OnboardingPage /></Guard>} />
          <Route path="welcome" element={<WelcomePage />} />
          <Route path="insights" element={<Guard permissions={['insights.view']}><InsightsPage /></Guard>} />
          <Route path="scenarios" element={<Guard permissions={['simulations.run']}><ScenariosPage /></Guard>} />
          <Route
            path="reports"
            element={<Guard permissions={['reports.view', 'reports.ops']}><ReportsPage /></Guard>}
          />
          <Route path="rules" element={<Guard permissions={['rules.view']}><RulesPage /></Guard>} />
          <Route path="data-flow" element={<Guard permissions={['dashboard.view', 'rules.view']}><HowItWorksPage /></Guard>} />
          <Route path="health" element={<Guard permissions={['ops.view']}><HealthPage /></Guard>} />
          <Route path="config" element={<Guard permissions={['config.view']}><ConfigPage /></Guard>} />
          <Route path="admin" element={<Guard permissions={['admin.view', 'audit.view']}><AdminPage /></Guard>} />
          <Route path="*" element={<Home />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
