import { useEffect } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { isDesktop } from '../api/client';
import logo from '../assets/logo.png';
import { useAuth } from '../auth/AuthContext';
import { useI18n, type MessageKey } from '../i18n';
import { Icon, type IconName } from './Icon';
import { TourProvider, tourSeen, useTour } from './Tour';

interface NavItem {
  to: string;
  label: MessageKey;
  icon: IconName;
  permissions: string[];
}

export const NAV: NavItem[] = [
  { to: '/overview', label: 'nav.overview', icon: 'overview', permissions: ['dashboard.view'] },
  { to: '/explorer', label: 'nav.explorer', icon: 'explorer', permissions: ['cases.view'] },
  { to: '/workforce', label: 'nav.workforce', icon: 'people', permissions: ['workforce.view'] },
  { to: '/workplace', label: 'nav.workplace', icon: 'clock', permissions: ['workplace.view'] },
  { to: '/onboarding', label: 'nav.onboarding', icon: 'calendar', permissions: ['onboarding.manage'] },
  { to: '/learning', label: 'nav.learning', icon: 'learning', permissions: ['learning.view'] },
  { to: '/insights', label: 'nav.insights', icon: 'insights', permissions: ['insights.view'] },
  { to: '/scenarios', label: 'nav.scenarios', icon: 'scenarios', permissions: ['simulations.run'] },
  { to: '/reports', label: 'nav.reports', icon: 'reports', permissions: ['reports.view', 'reports.ops'] },
  { to: '/rules', label: 'nav.rules', icon: 'rules', permissions: ['rules.view'] },
  { to: '/data-flow', label: 'nav.dataFlow', icon: 'flow', permissions: ['dashboard.view', 'rules.view'] },
  { to: '/health', label: 'nav.health', icon: 'health', permissions: ['ops.view'] },
  { to: '/config', label: 'nav.config', icon: 'tune', permissions: ['config.view'] },
  { to: '/admin', label: 'nav.admin', icon: 'admin', permissions: ['admin.view', 'audit.view'] },
  // Everyone: the welcome journey (no permission needed).
  { to: '/welcome', label: 'nav.welcome', icon: 'flag', permissions: [] },
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

function TourButton() {
  const { t } = useI18n();
  const { user } = useAuth();
  const { start, active } = useTour();
  // The Chief HR Officer is offered the tour automatically on first sign-in.
  useEffect(() => {
    if (user && user.roles.some((r) => r.code === 'hr_chief') && !tourSeen(user.username)) {
      const h = window.setTimeout(start, 900);
      return () => window.clearTimeout(h);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.username]);
  return (
    <button className="btn small tour-start" onClick={start} disabled={active} data-tour="tour-button">
      <Icon name="compass" size={16} />
      {t('tour.start')}
    </button>
  );
}

export default function Layout() {
  return (
    <TourProvider>
      <Shell />
    </TourProvider>
  );
}

function Shell() {
  const { user, logout, can } = useAuth();
  const { t, tx, pick } = useI18n();
  const isEmployee = !!user?.employee_id && user.roles.every((r) => r.code === 'employee');

  return (
    <div className="shell">
      <aside className="sidebar" aria-label="Main navigation">
        <div className="brand">
          <img className="brand-logo" src={logo} alt="Bank of Palestine · بنك فلسطين" width={56} height={56} />
          <div>
            <div className="brand-name">{t('app.name')}</div>
            <div className="brand-tag">{t('app.tagline')}</div>
          </div>
        </div>
        {NAV.filter((item) => !item.permissions.length || can(...item.permissions)).map((item) => (
          <NavLink
            key={item.to}
            to={item.to === '/learning' && isEmployee ? `/learning/${user?.employee_id}` : item.to}
            className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
          >
            <Icon name={item.icon} />
            {t(
              item.to === '/learning' && isEmployee
                ? 'nav.myLearning'
                : item.to === '/workplace' && isEmployee
                  ? 'nav.myWorkplace'
                  : item.label,
            )}
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
          <TourButton />
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
