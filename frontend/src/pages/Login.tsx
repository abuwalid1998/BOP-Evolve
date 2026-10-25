import { useEffect, useState, type FormEvent } from 'react';
import { api, ApiError, getApiBase, isDesktop } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { DemoBanner, LanguageToggle } from '../components/Layout';
import { Icon } from '../components/Icon';
import { Field } from '../components/ui';
import { useI18n } from '../i18n';

interface DemoAccount {
  username: string;
  display_name: string;
  display_name_ar: string | null;
  role: string;
}

function DesktopServerSettings() {
  const { t } = useI18n();
  const [url, setUrl] = useState(getApiBase());
  const [result, setResult] = useState<string | null>(null);

  const test = async () => {
    const res = await window.bopDesktop!.testServer(url);
    setResult(res.ok ? t('desktop.connected') : `${t('desktop.failed')}${res.error ? ` — ${res.error}` : ''}`);
  };
  const save = async () => {
    await window.bopDesktop!.setServerUrl(url);
    window.location.reload();
  };

  return (
    <details className="card" style={{ padding: 14 }}>
      <summary className="row" style={{ cursor: 'pointer' }}>
        <Icon name="server" size={16} />
        <strong>{t('desktop.server')}</strong>
        <span className="subtle mono">{getApiBase()}</span>
      </summary>
      <div className="stack" style={{ marginTop: 12, gap: 10 }}>
        <Field label={t('desktop.serverUrl')} help={t('desktop.serverHelp')}>
          <input value={url} onChange={(e) => setUrl(e.target.value)} dir="ltr" spellCheck={false} />
        </Field>
        <div className="row">
          <button type="button" className="btn small" onClick={test}>
            {t('desktop.test')}
          </button>
          <button type="button" className="btn small primary" onClick={save}>
            {t('desktop.saveRestart')}
          </button>
          {result && <span className="subtle">{result}</span>}
        </div>
      </div>
    </details>
  );
}

export default function LoginPage() {
  const { login, expired } = useAuth();
  const { t, tx, pick } = useI18n();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [accounts, setAccounts] = useState<DemoAccount[]>([]);

  useEffect(() => {
    api
      .get<DemoAccount[]>('/api/auth/demo-accounts')
      .then(setAccounts)
      .catch(() => setAccounts([]));
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 0 ? t('auth.serverUnreachable') : t('auth.invalid'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100%' }}>
      <DemoBanner />
      <div className="login-wrap" style={{ flex: 1 }}>
        <section className="login-hero">
          <div className="brand-mark" style={{ background: '#fff', color: 'var(--brand)' }}>
            B
          </div>
          <div>
            <h1>{t('app.name')}</h1>
            <p>{t('app.tagline')}</p>
          </div>
          <p style={{ fontSize: 13 }}>{t('learning.metaphor')}</p>
        </section>
        <section className="login-panel">
          <form className="login-form" onSubmit={submit}>
            <div className="row between">
              <h2>{t('auth.signIn')}</h2>
              <LanguageToggle />
            </div>
            {expired && <div className="callout info">{t('auth.sessionExpired')}</div>}
            {isDesktop() && <DesktopServerSettings />}
            <Field label={t('auth.username')}>
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                dir="ltr"
                required
              />
            </Field>
            <Field label={t('auth.password')}>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                dir="ltr"
                required
              />
            </Field>
            {error && (
              <div className="error-box" role="alert">
                {error}
              </div>
            )}
            <button className="btn primary" type="submit" disabled={busy}>
              {t('auth.signIn')}
            </button>
            <p className="subtle">{t('auth.demoHint')}</p>
            {accounts.length > 0 && (
              <div className="stack" style={{ gap: 8 }}>
                <strong>{t('auth.demoAccounts')}</strong>
                <span className="subtle">{t('auth.pickAccount')}</span>
                <div className="account-grid">
                  {accounts.map((a) => (
                    <button
                      type="button"
                      key={`${a.username}-${a.role}`}
                      className={username === a.username ? 'selected' : ''}
                      onClick={() => setUsername(a.username)}
                      title={pick(a.display_name, a.display_name_ar)}
                    >
                      <div style={{ fontWeight: 600 }}>{tx('role', a.role)}</div>
                      <div className="mono subtle">{a.username}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </form>
        </section>
      </div>
    </div>
  );
}
