import { useEffect, useState, type FormEvent } from 'react';
import { api, ApiError, getApiBase, isDesktop } from '../api/client';
import logo from '../assets/logo.png';
import { useAuth } from '../auth/AuthContext';
import { FlowCanvas } from '../components/FlowCanvas';
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

function ActivateForm({ onBack }: { onBack: () => void }) {
  const { activate } = useAuth();
  const { t } = useI18n();
  const [username, setUsername] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (password !== confirm) {
      setError(t('activate.mismatch'));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await activate(username.trim(), code.trim(), password);
    } catch (err) {
      const code = err instanceof ApiError ? (err.detail as { code?: string } | undefined)?.code : undefined;
      setError(
        err instanceof ApiError && err.status === 0
          ? t('auth.serverUnreachable')
          : code === 'too_short' || code === 'needs_letters_and_digits'
            ? t('activate.weak')
            : code === 'expired'
              ? t('activate.expired')
              : t('activate.invalid'),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="login-form" onSubmit={submit}>
      <div className="row between">
        <h2>{t('activate.title')}</h2>
        <LanguageToggle />
      </div>
      <p className="subtle">{t('activate.intro')}</p>
      <Field label={t('activate.username')} help={t('activate.usernameHelp')}>
        <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" dir="ltr" required />
      </Field>
      <Field label={t('activate.code')} help={t('activate.codeHelp')}>
        <input
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          autoComplete="one-time-code"
          dir="ltr"
          placeholder="XXXXX-XXXXX"
          required
        />
      </Field>
      <Field label={t('activate.password')} help={t('activate.passwordHelp')}>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" dir="ltr" required />
      </Field>
      <Field label={t('activate.confirm')}>
        <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" dir="ltr" required />
      </Field>
      {error && (
        <div className="error-box" role="alert">
          {error}
        </div>
      )}
      <button className="btn primary" type="submit" disabled={busy}>
        {t('activate.submit')}
      </button>
      <button type="button" className="btn ghost" onClick={onBack}>
        {t('activate.back')}
      </button>
    </form>
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
  const [activating, setActivating] = useState(false);

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
          <FlowCanvas className="hero-flow" density={1.5} />
          <img className="hero-logo" src={logo} alt="Bank of Palestine · بنك فلسطين" width={148} height={148} />
          <div>
            <h1>{t('app.name')}</h1>
            <p>{t('app.tagline')}</p>
          </div>
          <p style={{ fontSize: 13 }}>{t('learning.metaphor')}</p>
        </section>
        <section className="login-panel">
          {activating ? (
            <ActivateForm onBack={() => setActivating(false)} />
          ) : (
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
            <button type="button" className="btn ghost" onClick={() => setActivating(true)} data-tour="activate">
              <Icon name="key" size={16} /> {t('activate.link')}
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
          )}
        </section>
      </div>
    </div>
  );
}
