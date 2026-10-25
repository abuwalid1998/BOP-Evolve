import { useEffect, useState, type FormEvent } from 'react';
import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { Icon } from '../components/Icon';
import { PageBrief } from '../components/PageBrief';
import { Badge, Card, Empty, ErrorBox, Field, Loading, PageHead, Toast } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useI18n, type MessageKey } from '../i18n';

// ------------------------------------------------------------------- types
interface Connection {
  id: string;
  builtin: boolean;
  name: string;
  engine: string;
  host: string | null;
  port: number | null;
  database: string | null;
  username: string | null;
  schema: string | null;
  sslmode?: string;
  notes?: string | null;
  password_source: 'stored' | 'env' | 'none' | 'environment';
  password_env?: string | null;
  host_allowed: boolean;
  last_test_at?: string | null;
  last_test_ok?: boolean | null;
  last_check_at?: string | null;
  last_check_status?: string | null;
}

interface Privileges {
  supported: boolean;
  user?: string;
  database?: string;
  schema?: string | null;
  server_version?: string;
  read_only?: boolean;
  superuser?: boolean;
  can_create_tables?: boolean;
  ssl?: boolean;
  owned_tables?: string[];
  not_owned_tables?: string[];
}

interface TestResult {
  ok: boolean;
  latency_ms?: number;
  error?: string;
  privileges?: Privileges;
}

type Category = 'safe' | 'risky' | 'destructive';

interface PlanItem {
  id: string;
  category: Category;
  kind: string;
  table: string | null;
  column: string | null;
  description: string;
  sql: string;
  allowed: boolean;
  reason: string | null;
}

interface SchemaResult {
  connection: Connection;
  checked_at: string;
  status: 'valid' | 'invalid' | 'empty' | 'error';
  error?: string;
  revision?: { current: string | null; head: string | null };
  summary?: {
    expected_tables: number;
    present_tables: number;
    missing_tables: number;
    differing_tables: number;
    extra_tables: number;
    changes: Record<Category, number>;
  };
  tables?: { name: string; status: 'ok' | 'missing' | 'differs'; issues: { description: string; category: Category }[] }[];
  extra_tables?: string[];
  plan?: PlanItem[];
  plan_hash?: string;
  privileges?: Privileges;
  warnings?: string[];
  can_apply: boolean;
  can_apply_risky: boolean;
  stamp_only: boolean;
  blockers: string[];
}

interface SettingDef {
  key: string;
  category: string;
  kind: 'int' | 'float' | 'enum' | 'str';
  default: number | string;
  min: number | null;
  max: number | null;
  step: number | null;
  choices: string[];
  value: number | string;
  overridden: boolean;
}

type SettingError = { code: string; min?: number; max?: number; total?: number };

const STATUS_TONE = { valid: 'ok', invalid: 'warn', empty: 'info', error: 'bad' } as const;
const CATEGORY_TONE = { safe: 'ok', risky: 'warn', destructive: 'neutral' } as const;
const WEIGHT_KEYS = [
  'learning.weight_understanding',
  'learning.weight_action_completion',
  'learning.weight_follow_up',
  'learning.weight_recurrence_trend',
];

// -------------------------------------------------------------- database tab
function connectionName(c: Connection, t: ReturnType<typeof useI18n>['t']) {
  return c.builtin ? t('db.currentName') : c.name;
}

function passwordLabel(c: Connection, t: ReturnType<typeof useI18n>['t']) {
  if (c.password_source === 'stored') return t('db.pw.stored');
  if (c.password_source === 'env') return t('db.pw.env', { name: c.password_env ?? '' });
  if (c.password_source === 'environment') return t('db.pw.environment');
  return t('db.pw.none');
}

function ConnectionForm({
  initial,
  onSaved,
  onCancel,
}: {
  initial: Connection | null;
  onSaved: (c: Connection) => void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const [form, setForm] = useState({
    name: initial?.name ?? '',
    host: initial?.host ?? '',
    port: String(initial?.port ?? 5432),
    database: initial?.database ?? '',
    username: initial?.username ?? '',
    password: '',
    mode: initial?.password_source === 'env' ? 'env' : 'stored',
    password_env: initial?.password_env ?? 'BOP_DBPASS_',
    clear_password: false,
    sslmode: initial?.sslmode ?? 'prefer',
    schema_name: initial?.schema ?? 'public',
    notes: initial?.notes ?? '',
  });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [draftResult, setDraftResult] = useState<TestResult | null>(null);
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  const body = () => ({
    name: form.name.trim(),
    engine: 'postgresql',
    host: form.host.trim(),
    port: Number(form.port),
    database: form.database.trim(),
    username: form.username.trim(),
    password: form.mode === 'stored' && form.password ? form.password : null,
    password_env: form.mode === 'env' ? form.password_env.trim() : null,
    clear_password: form.mode === 'stored' && form.clear_password,
    sslmode: form.sslmode,
    schema_name: form.schema_name.trim(),
    notes: form.notes.trim() || null,
  });

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      const saved = initial
        ? await api.put<Connection>(`/api/config/db-connections/${initial.id}`, body())
        : await api.post<Connection>('/api/config/db-connections', body());
      onSaved(saved);
    });
  };

  return (
    <Card title={initial ? t('db.form.edit') : t('db.form.new')}>
      <form className="stack" style={{ gap: 12 }} onSubmit={submit}>
        <div className="grid grid-3">
          <Field label={t('db.form.name')}>
            <input value={form.name} onChange={set('name')} required minLength={2} maxLength={80} />
          </Field>
          <Field label={t('db.form.engine')}>
            <select value="postgresql" disabled>
              <option value="postgresql">PostgreSQL</option>
            </select>
          </Field>
          <Field label={t('db.form.sslmode')}>
            <select value={form.sslmode} onChange={set('sslmode')}>
              {['disable', 'allow', 'prefer', 'require', 'verify-ca', 'verify-full'].map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('db.form.host')}>
            <input value={form.host} onChange={set('host')} required dir="ltr" spellCheck={false} />
          </Field>
          <Field label={t('db.form.port')}>
            <input type="number" min={1} max={65535} value={form.port} onChange={set('port')} required dir="ltr" />
          </Field>
          <Field label={t('db.form.database')}>
            <input value={form.database} onChange={set('database')} required dir="ltr" spellCheck={false} />
          </Field>
          <Field label={t('db.form.username')}>
            <input value={form.username} onChange={set('username')} required dir="ltr" autoComplete="off" spellCheck={false} />
          </Field>
          <Field label={t('db.form.schema')}>
            <input value={form.schema_name} onChange={set('schema_name')} required dir="ltr" spellCheck={false} />
          </Field>
          <Field label={t('db.form.passwordSource')}>
            <select value={form.mode} onChange={set('mode')}>
              <option value="stored">{t('db.form.passwordStored')}</option>
              <option value="env">{t('db.form.passwordEnv')}</option>
            </select>
          </Field>
        </div>
        {form.mode === 'stored' ? (
          <div className="grid grid-3">
            <Field label={t('db.form.password')} help={initial?.password_source === 'stored' ? t('db.form.passwordKeep') : undefined}>
              <input
                type="password"
                value={form.password}
                onChange={set('password')}
                autoComplete="new-password"
                dir="ltr"
                disabled={form.clear_password}
              />
            </Field>
            {initial?.password_source === 'stored' && (
              <label className="check" style={{ alignSelf: 'center' }}>
                <input
                  type="checkbox"
                  checked={form.clear_password}
                  onChange={(e) => setForm({ ...form, clear_password: e.target.checked, password: '' })}
                />
                {t('db.form.clearPassword')}
              </label>
            )}
          </div>
        ) : (
          <Field label={t('db.form.passwordEnvName')} help={t('db.form.passwordEnvHelp')}>
            <input value={form.password_env} onChange={set('password_env')} dir="ltr" spellCheck={false} pattern="BOP_DBPASS_[A-Z0-9_]+" />
          </Field>
        )}
        <Field label={t('db.form.notes')}>
          <input value={form.notes} onChange={set('notes')} maxLength={500} />
        </Field>
        <ErrorBox error={error} />
        {draftResult && <TestResultView result={draftResult} />}
        <div className="row">
          <button className="btn primary" disabled={busy}>
            {t('db.form.save')}
          </button>
          <button
            type="button"
            className="btn"
            disabled={busy || !form.host || !form.database || !form.username}
            onClick={() => run(async () => setDraftResult(await api.post<TestResult>('/api/config/db-connections/test-draft', body())))}
          >
            {t('db.form.testDraft')}
          </button>
          <button type="button" className="btn ghost" onClick={onCancel}>
            {t('common.cancel')}
          </button>
        </div>
      </form>
    </Card>
  );
}

function TestResultView({ result }: { result: TestResult }) {
  const { t } = useI18n();
  const p = result.privileges;
  const yesNo = (v?: boolean) => (v ? <Badge tone="ok">{t('common.yes')}</Badge> : <Badge tone="neutral">{t('common.no')}</Badge>);
  return (
    <div className={`callout ${result.ok ? 'info' : 'bad'}`} style={{ flexDirection: 'column', gap: 10 }}>
      <strong>
        {result.ok ? t('db.result.ok', { ms: result.latency_ms ?? 0 }) : t('db.result.failed')}
      </strong>
      {result.error && <span className="mono" style={{ whiteSpace: 'pre-wrap' }}>{result.error}</span>}
      {p && p.supported && (
        <dl className="dl">
          <dt>{t('db.priv.user')}</dt>
          <dd className="mono">{p.user}</dd>
          <dt>{t('db.priv.server')}</dt>
          <dd className="mono">{p.server_version}</dd>
          <dt>{t('db.priv.ssl')}</dt>
          <dd>{yesNo(p.ssl)}</dd>
          <dt>{t('db.priv.readOnly')}</dt>
          <dd>{p.read_only ? <Badge tone="warn">{t('common.yes')}</Badge> : <Badge tone="ok">{t('common.no')}</Badge>}</dd>
          <dt>{t('db.priv.superuser')}</dt>
          <dd>{yesNo(p.superuser)}</dd>
          <dt>{t('db.priv.createTables')}</dt>
          <dd>{yesNo(p.can_create_tables)}</dd>
          <dt>{t('db.form.schema')}</dt>
          <dd>
            <span className="mono">{p.schema ?? '—'}</span>{' '}
            <span className="subtle">
              {t('db.priv.owned', {
                owned: p.owned_tables?.length ?? 0,
                total: (p.owned_tables?.length ?? 0) + (p.not_owned_tables?.length ?? 0),
              })}
            </span>
          </dd>
        </dl>
      )}
      {p && !p.supported && <span className="subtle">{t('db.priv.unsupported')}</span>}
    </div>
  );
}

function ApplyDialog({
  result,
  count,
  onCancel,
  onConfirm,
  busy,
}: {
  result: SchemaResult;
  count: number;
  onCancel: () => void;
  onConfirm: (typed: string) => void;
  busy: boolean;
}) {
  const { t } = useI18n();
  const [typed, setTyped] = useState('');
  const database = result.connection.database ?? '';
  const host = result.connection.host ?? 'localhost';
  return (
    <div className="modal-backdrop" role="presentation" onClick={onCancel}>
      <div className="modal card" role="dialog" aria-modal="true" aria-labelledby="apply-title" onClick={(e) => e.stopPropagation()}>
        <h2 id="apply-title">{t('db.confirm.title')}</h2>
        <p className="muted">
          {result.stamp_only
            ? t('db.confirm.stampBody', { head: result.revision?.head ?? '', database, host })
            : t('db.confirm.body', { n: count, database, host })}
        </p>
        <Field label={t('db.confirm.type')}>
          <input value={typed} onChange={(e) => setTyped(e.target.value)} dir="ltr" autoFocus placeholder={database} />
        </Field>
        <div className="row" style={{ justifyContent: 'flex-end', marginTop: 14 }}>
          <button className="btn" onClick={onCancel}>
            {t('common.cancel')}
          </button>
          <button className="btn primary" disabled={busy || typed !== database} onClick={() => onConfirm(typed)}>
            {result.stamp_only ? t('db.plan.stampOnly') : t('db.plan.apply')}
          </button>
        </div>
      </div>
    </div>
  );
}

function SchemaResultView({
  result,
  canManage,
  onApplied,
}: {
  result: SchemaResult;
  canManage: boolean;
  onApplied: (next: SchemaResult, message: string) => void;
}) {
  const { t, tx, fmtDate, fmtNumber } = useI18n();
  const [onlyIssues, setOnlyIssues] = useState(result.status === 'invalid');
  const [includeRisky, setIncludeRisky] = useState(false);
  const [dialog, setDialog] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setIncludeRisky(false);
    setOnlyIssues(result.status === 'invalid');
  }, [result.plan_hash, result.status]);

  const plan = result.plan ?? [];
  const selected = plan.filter((c) => c.category === 'safe' || (includeRisky && c.category === 'risky'));
  const sqlScript = selected.map((c) => c.sql.replace(/;?\s*$/, ';')).join('\n\n');

  const apply = async (typed: string) => {
    setBusy(true);
    setError(null);
    try {
      const outcome = await api.post<{ applied: unknown[]; stamped_revision: string | null; check: SchemaResult }>(
        `/api/config/db-connections/${result.connection.id}/apply`,
        { plan_hash: result.plan_hash, include_risky: includeRisky, confirm_database: typed },
      );
      setDialog(false);
      const parts = [t('db.applied', { n: outcome.applied.length })];
      if (outcome.stamped_revision) parts.push(t('db.stamped', { rev: outcome.stamped_revision }));
      onApplied(outcome.check, parts.join(' '));
    } catch (err) {
      setError(err as ApiError);
      setDialog(false);
    } finally {
      setBusy(false);
    }
  };

  const copySql = async () => {
    try {
      await navigator.clipboard.writeText(sqlScript);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable */
    }
  };

  const tables = (result.tables ?? []).filter((tbl) => !onlyIssues || tbl.status !== 'ok');
  const s = result.summary;

  return (
    <Card
      title={
        <span className="row" style={{ gap: 8 }}>
          {t('db.schema.title')}
          <Badge tone={STATUS_TONE[result.status]}>{t(`db.schema.status.${result.status}` as MessageKey)}</Badge>
        </span>
      }
      subtitle={`${connectionName(result.connection, t)} · ${fmtDate(result.checked_at, true)}`}
    >
      <div className="stack">
        {result.error && <ErrorBox error={new Error(result.error)} />}
        {result.revision && (
          <span className="subtle">
            {t('db.schema.revision', {
              current: result.revision.current ?? t('db.schema.revisionNone'),
              head: result.revision.head ?? '—',
            })}
          </span>
        )}
        {(result.warnings ?? []).map((w) => (
          <div key={w} className="callout" style={{ padding: '8px 12px' }}>
            {t(`db.warning.${w}` as MessageKey)}
          </div>
        ))}
        {s && (
          <div className="config-kpis">
            {(
              [
                ['db.schema.expected', s.expected_tables],
                ['db.schema.present', s.present_tables],
                ['db.schema.missing', s.missing_tables],
                ['db.schema.differing', s.differing_tables],
                ['db.schema.extra', s.extra_tables],
              ] as const
            ).map(([label, value]) => (
              <div key={label}>
                <span className="subtle">{t(label)}</span>
                <strong>{fmtNumber(value)}</strong>
              </div>
            ))}
          </div>
        )}

        {result.tables && (
          <div>
            <div className="row between" style={{ marginBottom: 6 }}>
              <h3>{t('db.schema.details')}</h3>
              <label className="check">
                <input type="checkbox" checked={onlyIssues} onChange={(e) => setOnlyIssues(e.target.checked)} />
                {t('db.schema.onlyIssues')}
              </label>
            </div>
            {tables.length === 0 ? (
              <Empty>{t('db.schema.noIssues')}</Empty>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>{t('db.schema.table')}</th>
                      <th>{t('explorer.status')}</th>
                      <th>{t('db.schema.details')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tables.map((tbl) => (
                      <tr key={tbl.name}>
                        <td className="mono">{tbl.name}</td>
                        <td>
                          <Badge tone={tbl.status === 'ok' ? 'ok' : tbl.status === 'missing' ? 'bad' : 'warn'}>
                            {t(`db.schema.tableStatus.${tbl.status}` as MessageKey)}
                          </Badge>
                        </td>
                        <td>
                          {tbl.issues.length === 0 ? (
                            <span className="subtle">{tbl.status === 'missing' ? t('db.schema.tableStatus.missing') : '—'}</span>
                          ) : (
                            <ul className="config-issues">
                              {tbl.issues.map((issue, i) => (
                                <li key={i}>
                                  <Badge tone={CATEGORY_TONE[issue.category]}>{tx('db.plan.category', issue.category)}</Badge>{' '}
                                  <span className="mono">{issue.description}</span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {(result.extra_tables ?? []).length > 0 && (
          <div>
            <h3>{t('db.schema.extraTables')}</h3>
            <div className="row" style={{ gap: 6, marginTop: 6 }}>
              {result.extra_tables!.map((name) => (
                <span key={name} className="badge mono">
                  {name}
                </span>
              ))}
            </div>
          </div>
        )}

        {result.status !== 'error' && (
          <div className="stack" style={{ gap: 10 }}>
            <h3>{t('db.plan.title')}</h3>
            {plan.length === 0 && <span className="subtle">{t('db.plan.none')}</span>}
            {(['safe', 'risky', 'destructive'] as const).map((category) => {
              const items = plan.filter((c) => c.category === category);
              if (items.length === 0) return null;
              return (
                <details key={category} className="config-plan" open={category !== 'destructive'}>
                  <summary>
                    <Badge tone={CATEGORY_TONE[category]}>{tx('db.plan.category', category)}</Badge>{' '}
                    <strong>{fmtNumber(items.length)}</strong>{' '}
                    <span className="subtle">{t(`db.plan.help.${category}` as MessageKey)}</span>
                  </summary>
                  <ul>
                    {items.map((c) => (
                      <li key={c.id}>
                        <div className="row" style={{ gap: 6 }}>
                          {category !== 'destructive' &&
                            (c.allowed ? (
                              <Badge tone="ok">{t('db.plan.allowed')}</Badge>
                            ) : (
                              <Badge tone="bad">{t('db.plan.blocked')}</Badge>
                            ))}
                          <span className="mono">{c.description}</span>
                        </div>
                        {c.reason && category !== 'destructive' && <div className="subtle">{c.reason}</div>}
                        {category !== 'destructive' && (
                          <details>
                            <summary className="subtle">{t('db.plan.sql')}</summary>
                            <pre className="config-sql mono">{c.sql}</pre>
                          </details>
                        )}
                      </li>
                    ))}
                  </ul>
                </details>
              );
            })}

            <div className="row" style={{ gap: 14 }}>
              {(result.summary?.changes.risky ?? 0) > 0 && (
                <label className="check" title={result.can_apply_risky ? '' : t('db.blocker.risky')}>
                  <input
                    type="checkbox"
                    checked={includeRisky}
                    disabled={!result.can_apply_risky}
                    onChange={(e) => setIncludeRisky(e.target.checked)}
                  />
                  {t('db.plan.includeRisky')}
                </label>
              )}
              {selected.length > 0 && (
                <button className="btn small" type="button" onClick={copySql}>
                  {copied ? t('db.plan.copied') : t('db.plan.copySql')}
                </button>
              )}
              {canManage && (selected.length > 0 || result.stamp_only) && (
                <button
                  className="btn primary"
                  disabled={!result.can_apply || busy}
                  onClick={() => setDialog(true)}
                >
                  {result.stamp_only ? t('db.plan.stampOnly') : t('db.plan.applyCount', { n: selected.length })}
                </button>
              )}
            </div>
            {result.blockers
              .filter((b) => (canManage ? b !== 'nothing_to_apply' : b === 'app_permission'))
              .map((b) => (
                <span key={b} className="subtle">
                  {t(`db.blocker.${b}` as MessageKey)}
                </span>
              ))}
            {includeRisky === false && !result.can_apply_risky && (result.summary?.changes.risky ?? 0) > 0 && canManage && (
              <span className="subtle">{t('db.blocker.risky')}</span>
            )}
            <ErrorBox error={error} />
          </div>
        )}
      </div>
      {dialog && <ApplyDialog result={result} count={selected.length} busy={busy} onCancel={() => setDialog(false)} onConfirm={apply} />}
    </Card>
  );
}

function DatabaseTab({ canManage }: { canManage: boolean }) {
  const { t, fmtDate } = useI18n();
  const list = useApi<Connection[]>('/api/config/db-connections');
  const [selected, setSelected] = useState('current');
  const [editing, setEditing] = useState<Connection | 'new' | null>(null);
  const [tests, setTests] = useState<Record<string, TestResult>>({});
  const [checks, setChecks] = useState<Record<string, SchemaResult>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const flash = (message: string) => {
    setToast(message);
    setTimeout(() => setToast(null), 3000);
  };

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(null);
    }
  };

  const test = (id: string) =>
    run(`${id}:test`, async () => {
      setSelected(id);
      const result = await api.post<TestResult>(`/api/config/db-connections/${id}/test`);
      setTests((prev) => ({ ...prev, [id]: result }));
      list.reload();
    });

  const check = (id: string) =>
    run(`${id}:check`, async () => {
      setSelected(id);
      const result = await api.post<SchemaResult>(`/api/config/db-connections/${id}/schema-check`);
      setChecks((prev) => ({ ...prev, [id]: result }));
      list.reload();
    });

  const remove = (c: Connection) => {
    if (!window.confirm(t('db.deleteConfirm', { name: c.name }))) return;
    run(`${c.id}:delete`, async () => {
      await api.del(`/api/config/db-connections/${c.id}`);
      setSelected('current');
      list.reload();
    });
  };

  if (!list.data) return list.loading ? <Loading /> : <ErrorBox error={list.error} onRetry={list.reload} />;
  const current = list.data.find((c) => c.id === selected) ?? list.data[0];

  return (
    <div className="stack">
      <ErrorBox error={error} />
      <div className="config-db">
        <Card
          title={t('db.connections')}
          subtitle={t('db.connectionsHelp')}
          actions={
            canManage && (
              <button className="btn small primary" onClick={() => setEditing('new')}>
                {t('db.add')}
              </button>
            )
          }
        >
          <ul className="config-connections">
            {list.data.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  className={`config-connection ${c.id === current.id ? 'selected' : ''}`}
                  onClick={() => setSelected(c.id)}
                  aria-pressed={c.id === current.id}
                >
                  <span className="row between">
                    <strong>{connectionName(c, t)}</strong>
                    <span className="row" style={{ gap: 4 }}>
                      {c.builtin && <Badge tone="brand">{t('db.builtin')}</Badge>}
                      {c.last_check_status && (
                        <Badge tone={STATUS_TONE[c.last_check_status as keyof typeof STATUS_TONE] ?? 'neutral'}>
                          {t(`db.schema.status.${c.last_check_status}` as MessageKey)}
                        </Badge>
                      )}
                    </span>
                  </span>
                  <span className="mono subtle">
                    {c.engine}://{c.username ? `${c.username}@` : ''}
                    {c.host ?? 'local'}
                    {c.port ? `:${c.port}` : ''}/{c.database}
                    {c.schema ? ` · ${c.schema}` : ''}
                  </span>
                  <span className="subtle">{passwordLabel(c, t)}</span>
                  {!c.host_allowed && <Badge tone="bad">{t('db.hostBlocked')}</Badge>}
                </button>
              </li>
            ))}
          </ul>
        </Card>

        <div className="stack">
          {editing ? (
            <ConnectionForm
              initial={editing === 'new' ? null : editing}
              onCancel={() => setEditing(null)}
              onSaved={(saved) => {
                setEditing(null);
                setSelected(saved.id);
                list.reload();
                flash(t('case.saved'));
              }}
            />
          ) : (
            <Card
              title={
                <span className="row" style={{ gap: 8 }}>
                  <Icon name="database" />
                  {connectionName(current, t)}
                </span>
              }
              subtitle={current.builtin ? t('db.currentNote') : current.notes ?? undefined}
              actions={
                <>
                  <button className="btn small" disabled={!!busy} onClick={() => test(current.id)}>
                    {busy === `${current.id}:test` ? t('db.working') : t('db.test')}
                  </button>
                  <button className="btn small primary" disabled={!!busy} onClick={() => check(current.id)}>
                    {busy === `${current.id}:check` ? t('db.working') : t('db.check')}
                  </button>
                  {canManage && !current.builtin && (
                    <>
                      <button className="btn small ghost" onClick={() => setEditing(current)}>
                        {t('db.edit')}
                      </button>
                      <button className="btn small ghost danger" onClick={() => remove(current)}>
                        {t('db.delete')}
                      </button>
                    </>
                  )}
                </>
              }
            >
              <dl className="dl">
                <dt>{t('db.form.host')}</dt>
                <dd className="mono">
                  {current.host ?? '—'}
                  {current.port ? `:${current.port}` : ''}
                </dd>
                <dt>{t('db.form.database')}</dt>
                <dd className="mono">{current.database ?? '—'}</dd>
                <dt>{t('db.form.username')}</dt>
                <dd className="mono">{current.username ?? '—'}</dd>
                <dt>{t('db.form.schema')}</dt>
                <dd className="mono">{current.schema ?? '—'}</dd>
                {current.sslmode && (
                  <>
                    <dt>{t('db.form.sslmode')}</dt>
                    <dd className="mono">{current.sslmode}</dd>
                  </>
                )}
                {!current.builtin && (
                  <>
                    <dt>{t('db.lastTest')}</dt>
                    <dd>
                      {current.last_test_at ? fmtDate(current.last_test_at, true) : t('db.never')}{' '}
                      {current.last_test_ok === true && <Badge tone="ok">{t('common.yes')}</Badge>}
                      {current.last_test_ok === false && <Badge tone="bad">{t('db.result.failed')}</Badge>}
                    </dd>
                    <dt>{t('db.lastCheck')}</dt>
                    <dd>{current.last_check_at ? fmtDate(current.last_check_at, true) : t('db.never')}</dd>
                  </>
                )}
              </dl>
              {tests[current.id] && (
                <div style={{ marginTop: 14 }}>
                  <TestResultView result={tests[current.id]} />
                </div>
              )}
            </Card>
          )}
          {!editing && checks[current.id] && (
            <SchemaResultView
              result={checks[current.id]}
              canManage={canManage}
              onApplied={(next, message) => {
                setChecks((prev) => ({ ...prev, [current.id]: next }));
                list.reload();
                flash(message);
              }}
            />
          )}
        </div>
      </div>
      <Toast message={toast} />
    </div>
  );
}

// -------------------------------------------------------------- settings tab
function SettingsTab({ canManage }: { canManage: boolean }) {
  const { t } = useI18n();
  const data = useApi<{ definitions: SettingDef[]; learning_method_version: string }>('/api/config/settings');
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, SettingError>>({});
  const [failure, setFailure] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const defs = data.data?.definitions ?? [];
  const valueOf = (d: SettingDef) => (d.key in draft ? draft[d.key] : String(d.value));
  const weightTotal = WEIGHT_KEYS.reduce((sum, key) => {
    const d = defs.find((x) => x.key === key);
    return sum + (d ? Number(valueOf(d)) || 0 : 0);
  }, 0);
  const changed = Object.keys(draft).filter((key) => {
    const d = defs.find((x) => x.key === key);
    return d && draft[key] !== String(d.value);
  });

  const flash = (message: string) => {
    setToast(message);
    setTimeout(() => setToast(null), 2500);
  };

  const handle = async (fn: () => Promise<void>) => {
    setBusy(true);
    setFailure(null);
    setErrors({});
    try {
      await fn();
    } catch (err) {
      const apiErr = err as ApiError;
      const detail = apiErr.detail as { errors?: Record<string, SettingError> } | undefined;
      if (detail?.errors) setErrors(detail.errors);
      else setFailure(apiErr);
    } finally {
      setBusy(false);
    }
  };

  const save = () =>
    handle(async () => {
      const values: Record<string, string | number> = {};
      for (const key of changed) {
        const d = defs.find((x) => x.key === key)!;
        values[key] = d.kind === 'int' || d.kind === 'float' ? Number(draft[key]) : draft[key];
      }
      await api.put('/api/config/settings', { values });
      setDraft({});
      data.reload();
      flash(t('set.saved'));
    });

  const reset = (key: string) =>
    handle(async () => {
      await api.del(`/api/config/settings/${key}`);
      setDraft({});
      data.reload();
      flash(t('set.saved'));
    });

  if (!data.data) return data.loading ? <Loading /> : <ErrorBox error={data.error} onRetry={data.reload} />;

  const errorText = (e: SettingError) =>
    t(`set.error.${e.code}` as MessageKey, { min: e.min ?? '', max: e.max ?? '', total: e.total ?? '' });
  const display = (d: SettingDef, v: number | string) =>
    d.kind === 'enum' ? (v === 'ar' ? 'العربية' : v === 'en' ? 'English' : String(v)) : String(v);

  return (
    <div className="stack">
      {(['general', 'privacy', 'retention', 'learning'] as const).map((category) => (
        <Card
          key={category}
          title={t(`set.category.${category}` as MessageKey)}
          subtitle={
            category === 'learning'
              ? t('set.methodVersion', { v: data.data!.learning_method_version })
              : category === 'retention'
                ? t('set.retentionNote')
                : undefined
          }
        >
          {category === 'learning' && <div className="callout brand" style={{ marginBottom: 14 }}>{t('set.learningNote')}</div>}
          <div className="grid grid-2">
            {defs
              .filter((d) => d.category === category)
              .map((d) => (
                <div key={d.key} className="config-setting">
                  <Field label={t(`set.${d.key}` as MessageKey)} help={t(`set.${d.key}.help` as MessageKey)}>
                    {d.kind === 'enum' ? (
                      <select
                        value={valueOf(d)}
                        disabled={!canManage}
                        onChange={(e) => setDraft({ ...draft, [d.key]: e.target.value })}
                      >
                        {d.choices.map((c) => (
                          <option key={c} value={c}>
                            {display(d, c)}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type="number"
                        value={valueOf(d)}
                        min={d.min ?? undefined}
                        max={d.max ?? undefined}
                        step={d.step ?? (d.kind === 'int' ? 1 : 0.01)}
                        disabled={!canManage}
                        dir="ltr"
                        aria-invalid={!!errors[d.key]}
                        onChange={(e) => setDraft({ ...draft, [d.key]: e.target.value })}
                      />
                    )}
                  </Field>
                  <div className="row" style={{ gap: 8 }}>
                    <span className="subtle">{t('set.default', { value: display(d, d.default) })}</span>
                    {d.overridden && <Badge tone="info">{t('set.overridden')}</Badge>}
                    {d.overridden && canManage && (
                      <button className="btn small ghost" disabled={busy} onClick={() => reset(d.key)}>
                        {t('set.reset')}
                      </button>
                    )}
                  </div>
                  {errors[d.key] && <span className="config-error">{errorText(errors[d.key])}</span>}
                </div>
              ))}
          </div>
          {category === 'learning' && (
            <p className={Math.abs(weightTotal - 1) > 0.001 ? 'config-error' : 'subtle'} style={{ marginBottom: 0 }}>
              {t('set.weightsTotal', { total: weightTotal.toFixed(2) })}
            </p>
          )}
        </Card>
      ))}
      {canManage && changed.length > 0 && (
        <div className="config-savebar">
          <span className="subtle">{changed.length > 0 ? t('set.unsaved', { n: changed.length }) : ''}</span>
          <div className="row">
            <button className="btn" disabled={busy || changed.length === 0} onClick={() => { setDraft({}); setErrors({}); }}>
              {t('set.discard')}
            </button>
            <button className="btn primary" disabled={busy || changed.length === 0} onClick={save}>
              {t('set.save')}
            </button>
          </div>
        </div>
      )}
      <ErrorBox error={failure} />
      <Toast message={toast} />
    </div>
  );
}

// ------------------------------------------------------------- pipelines tab
interface PipelineConfig {
  id: string;
  code: string;
  name: string;
  source: string;
  state: string;
  schedule_seconds: number;
  freshness_sla_minutes: number;
  owner: string;
  runbook_url: string;
}

function PipelineRow({ p, canManage, onSaved }: { p: PipelineConfig; canManage: boolean; onSaved: () => void }) {
  const { t } = useI18n();
  const [form, setForm] = useState({
    schedule_seconds: String(p.schedule_seconds),
    freshness_sla_minutes: String(p.freshness_sla_minutes),
    owner: p.owner,
    runbook_url: p.runbook_url,
  });
  const [error, setError] = useState<ApiError | null>(null);
  const dirty =
    form.schedule_seconds !== String(p.schedule_seconds) ||
    form.freshness_sla_minutes !== String(p.freshness_sla_minutes) ||
    form.owner !== p.owner ||
    form.runbook_url !== p.runbook_url;

  const save = async () => {
    setError(null);
    try {
      await api.patch(`/api/config/pipelines/${p.id}`, {
        schedule_seconds: Number(form.schedule_seconds),
        freshness_sla_minutes: Number(form.freshness_sla_minutes),
        owner: form.owner,
        runbook_url: form.runbook_url,
      });
      onSaved();
    } catch (err) {
      setError(err as ApiError);
    }
  };

  return (
    <tr>
      <td>
        <strong>{p.name}</strong>
        <div className="subtle mono">{p.code}</div>
      </td>
      <td>
        <input type="number" min={30} max={86400} value={form.schedule_seconds} disabled={!canManage} dir="ltr"
          aria-label={t('pipe.schedule')} onChange={(e) => setForm({ ...form, schedule_seconds: e.target.value })} style={{ width: 110 }} />
      </td>
      <td>
        <input type="number" min={1} max={10080} value={form.freshness_sla_minutes} disabled={!canManage} dir="ltr"
          aria-label={t('pipe.sla')} onChange={(e) => setForm({ ...form, freshness_sla_minutes: e.target.value })} style={{ width: 110 }} />
      </td>
      <td>
        <input value={form.owner} disabled={!canManage} aria-label={t('pipe.owner')}
          onChange={(e) => setForm({ ...form, owner: e.target.value })} />
      </td>
      <td>
        <input value={form.runbook_url} disabled={!canManage} dir="ltr" aria-label={t('pipe.runbook')}
          onChange={(e) => setForm({ ...form, runbook_url: e.target.value })} />
        {error && <div className="config-error">{error.message}</div>}
      </td>
      <td>
        {canManage && (
          <button className="btn small primary" disabled={!dirty} onClick={save}>
            {t('common.save')}
          </button>
        )}
      </td>
    </tr>
  );
}

function PipelinesTab({ canManage }: { canManage: boolean }) {
  const { t } = useI18n();
  const data = useApi<PipelineConfig[]>('/api/config/pipelines');
  const [toast, setToast] = useState<string | null>(null);
  if (!data.data) return data.loading ? <Loading /> : <ErrorBox error={data.error} onRetry={data.reload} />;
  return (
    <Card title={t('pipe.title')} subtitle={t('pipe.help')}>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t('health.pipelines')}</th>
              <th>{t('pipe.schedule')}</th>
              <th>{t('pipe.sla')}</th>
              <th>{t('pipe.owner')}</th>
              <th>{t('pipe.runbook')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.data.map((p) => (
              <PipelineRow
                key={`${p.id}-${p.schedule_seconds}-${p.freshness_sla_minutes}-${p.owner}-${p.runbook_url}`}
                p={p}
                canManage={canManage}
                onSaved={() => {
                  data.reload();
                  setToast(t('pipe.saved'));
                  setTimeout(() => setToast(null), 2500);
                }}
              />
            ))}
          </tbody>
        </table>
      </div>
      <Toast message={toast} />
    </Card>
  );
}

// ----------------------------------------------------------- environment tab
interface Environment {
  app_env: string;
  demo_mode: boolean;
  auth_mode: string;
  log_level: string;
  worker_tick_seconds: number;
  database: { engine: string; host: string | null; port: number | null; database: string | null; username: string | null };
  alembic_head: string | null;
  config_secret_key_configured: boolean;
  db_allowed_hosts: string[];
  db_allowed_hosts_mode: 'list' | 'any' | 'none';
  employee_level_simulation_enabled: boolean;
  version: string;
}

function EnvironmentTab() {
  const { t } = useI18n();
  const { data, error, loading, reload } = useApi<Environment>('/api/config/environment');
  if (!data) return loading ? <Loading /> : <ErrorBox error={error} onRetry={reload} />;
  const db = data.database;
  return (
    <Card title={t('env.title')} subtitle={t('env.note')}>
      <dl className="dl">
        <dt>{t('env.appEnv')}</dt>
        <dd className="mono">{data.app_env} · v{data.version}</dd>
        <dt>{t('env.demoMode')}</dt>
        <dd>{data.demo_mode ? <Badge tone="warn">{t('common.yes')}</Badge> : <Badge tone="ok">{t('common.no')}</Badge>}</dd>
        <dt>{t('env.authMode')}</dt>
        <dd className="mono">{data.auth_mode}</dd>
        <dt>{t('env.logLevel')}</dt>
        <dd className="mono">{data.log_level}</dd>
        <dt>{t('env.workerTick')}</dt>
        <dd className="mono">{data.worker_tick_seconds}</dd>
        <dt>{t('env.database')}</dt>
        <dd className="mono">
          {db.engine}://{db.username ? `${db.username}@` : ''}
          {db.host ?? 'local'}
          {db.port ? `:${db.port}` : ''}/{db.database}
        </dd>
        <dt>{t('env.alembicHead')}</dt>
        <dd className="mono">{data.alembic_head}</dd>
        <dt>{t('env.secretKey')}</dt>
        <dd>
          {data.config_secret_key_configured ? (
            <Badge tone="ok">{t('env.secretKeyConfigured')}</Badge>
          ) : (
            <Badge tone="warn">{t('env.secretKeyDerived')}</Badge>
          )}
        </dd>
        <dt>{t('env.allowedHosts')}</dt>
        <dd>
          {data.db_allowed_hosts_mode === 'list' ? (
            <span className="mono">{data.db_allowed_hosts.join(', ')}</span>
          ) : data.db_allowed_hosts_mode === 'any' ? (
            <Badge tone="warn">{t('env.hostsAny')}</Badge>
          ) : (
            <Badge tone="neutral">{t('env.hostsNone')}</Badge>
          )}
        </dd>
        <dt>{t('env.employeeLevel')}</dt>
        <dd>{data.employee_level_simulation_enabled ? t('env.employeeLevelOn') : t('env.employeeLevelOff')}</dd>
      </dl>
    </Card>
  );
}

// ---------------------------------------------------------------------- page
type Tab = 'database' | 'settings' | 'pipelines' | 'environment';

export default function ConfigPage() {
  const { t } = useI18n();
  const { can } = useAuth();
  const canManage = can('config.manage');
  const [tab, setTab] = useState<Tab>('database');
  const tabs: Tab[] = ['database', 'settings', 'pipelines', 'environment'];
  return (
    <>
      <PageHead title={t('config.title')} subtitle={t('config.subtitle')} />
      <PageBrief page="config" />
      {!canManage && (
        <div className="callout info" style={{ marginBottom: 16 }}>
          {t('config.readOnly')}
        </div>
      )}
      <div className="tabs" role="tablist">
        {tabs.map((id) => (
          <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
            {t(`config.tab.${id}` as MessageKey)}
          </button>
        ))}
      </div>
      {tab === 'database' && <DatabaseTab canManage={canManage} />}
      {tab === 'settings' && <SettingsTab canManage={canManage} />}
      {tab === 'pipelines' && <PipelinesTab canManage={canManage} />}
      {tab === 'environment' && <EnvironmentTab />}
    </>
  );
}
