import { NavLink, Outlet } from 'react-router-dom';
import { isDesktop } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { useI18n, type MessageKey } from '../i18n';
import { Icon, type IconName } from './Icon';

interface NavItem {
  to: string;
  label: MessageKey;
  icon: IconName;
  permissions: string[];
}

export const NAV: NavItem[] = [
  { to: '/overview', label: 'nav.overview', icon: 'overview', permissions: ['dashboard.view'] },
  { to: '/explorer', label: 'nav.explorer', icon: 'explorer', permissions: ['cases.view'] },
  { to: '/learning', label: 'nav.learning', icon: 'learning', permissions: ['learning.view'] },
  { to: '/insights', label: 'nav.insights', icon: 'insights', permissions: ['insights.view'] },
  { to: '/scenarios', label: 'nav.scenarios', icon: 'scenarios', permissions: ['simulations.run'] },
  { to: '/reports', label: 'nav.reports', icon: 'reports', permissions: ['reports.view', 'reports.ops'] },
  { to: '/health', label: 'nav.health', icon: 'health', permissions: ['ops.view'] },
  { to: '/admin', label: 'nav.admin', icon: 'admin', permissions: ['admin.view', 'audit.view'] },
];

export function DemoBanner() {
  const { t } = useI18n();
  return (
    <div className="demo-banner" role="note">
      <span className="dot" aria-hidden />
      {t('demo.banner')}
    </div>
  );
}

export function LanguageToggle() {
  const { lang, setLang, t } = useI18n();
  return (
    <button
      className="btn small ghost"
      onClick={() => setLang(lang === 'en' ? 'ar' : 'en')}
      aria-label={t('lang.label')}
      lang={lang === 'en' ? 'ar' : 'en'}
    >
      <Icon name="globe" size={16} />
      {t('lang.switch')}
    </button>
  );
}

export default function Layout() {
  const { user, logout, can } = useAuth();
  const { t, tx, pick } = useI18n();
  const isEmployee = !!user?.employee_id && user.roles.every((r) => r.code === 'employee');

  return (
    <div className="shell">
      <aside className="sidebar" aria-label="Main navigation">
        <div className="brand">
          <div className="brand-mark" aria-hidden>
            B
          </div>
          <div>
            <div className="brand-name">{t('app.name')}</div>
            <div className="brand-tag">{t('app.tagline')}</div>
          </div>
        </div>
        {NAV.filter((item) => can(...item.permissions)).map((item) => (
          <NavLink
            key={item.to}
            to={item.to === '/learning' && isEmployee ? `/learning/${user?.employee_id}` : item.to}
            className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
          >
            <Icon name={item.icon} />
            {t(item.to === '/learning' && isEmployee ? 'nav.myLearning' : item.label)}
          </NavLink>
        ))}
        <div className="sidebar-foot">
          {t('demo.short')} · v0.1.0{isDesktop() ? ` · ${window.bopDesktop?.platform}` : ''}
        </div>
      </aside>
      <div className="main">
        <DemoBanner />
        <header className="topbar">
          <div className="spacer" />
          <LanguageToggle />
          {user && (
            <div className="user-chip">
              <strong>{pick(user.display_name, user.display_name_ar)}</strong>
              <small>{user.roles.map((r) => tx('role', r.code)).join(' · ')}</small>
            </div>
          )}
          <button className="btn small" onClick={logout}>
            <Icon name="logout" size={16} />
            {t('auth.signOut')}
          </button>
        </header>
        <main className="content" id="main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
