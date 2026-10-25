import { useState } from 'react';
import { api, ApiError, qs } from '../api/client';
import type { UnitRef } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Badge, Card, ErrorBox, Field, Loading, PageHead, Pager } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useI18n } from '../i18n';

type Tab = 'users' | 'roles' | 'policies' | 'sources' | 'audit' | 'config';

interface AdminUser {
  id: string;
  username: string;
  display_name: string;
  display_name_ar: string | null;
  status: string;
  grants: { id: string; role: string; scope_type: string; scope: UnitRef | null }[];
}

const ROLE_CODES = [
  'super_admin',
  'dept_head',
  'regional_manager',
  'branch_manager',
  'section_manager',
  'team_lead',
  'employee',
  'hr_ld',
  'risk_compliance',
  'data_ai_ops',
  'analyst',
];

function UsersTab() {
  const { t, tx, pick } = useI18n();
  const { can } = useAuth();
  const users = useApi<AdminUser[]>('/api/admin/users');
  const units = useApi<(UnitRef & { parent_id: string | null })[]>('/api/admin/org-units');
  const [form, setForm] = useState({ user: '', role: 'analyst', scope_type: 'global', scope_id: '' });
  const [error, setError] = useState<ApiError | null>(null);

  const call = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      users.reload();
    } catch (err) {
      setError(err as ApiError);
    }
  };

  if (!users.data) return users.loading ? <Loading /> : <ErrorBox error={users.error} />;
  return (
    <div className="stack">
      {can('admin.manage') && (
        <Card title={t('admin.grant')}>
          <form
            className="filters"
            onSubmit={(e) => {
              e.preventDefault();
              call(() =>
                api.post(`/api/admin/users/${form.user}/roles`, {
                  role: form.role,
                  scope_type: form.scope_type,
                  scope_id: form.scope_id || null,
                }),
              );
            }}
          >
            <Field label={t('auth.username')}>
              <select value={form.user} onChange={(e) => setForm({ ...form, user: e.target.value })} required>
                <option value="" />
                {users.data.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.username}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t('admin.roles')}>
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                {ROLE_CODES.map((r) => (
                  <option key={r} value={r}>
                    {tx('role', r)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t('admin.scope')}>
              <select value={form.scope_type} onChange={(e) => setForm({ ...form, scope_type: e.target.value, scope_id: '' })}>
                {['global', 'department', 'region', 'branch', 'section', 'self'].map((s) => (
                  <option key={s} value={s}>
                    {tx('scope', s)}
                  </option>
                ))}
              </select>
            </Field>
            {!['global', 'self'].includes(form.scope_type) && (
              <Field label={tx('scope', form.scope_type)}>
                <select value={form.scope_id} onChange={(e) => setForm({ ...form, scope_id: e.target.value })} required>
                  <option value="" />
                  {(units.data ?? [])
                    .filter((u) => u.type === form.scope_type)
                    .map((u) => (
                      <option key={u.id} value={u.id}>
                        {pick(u.name, u.name_ar)}
                      </option>
                    ))}
                </select>
              </Field>
            )}
            <div>
              <button className="btn primary">{t('admin.grant')}</button>
            </div>
          </form>
          <ErrorBox error={error} />
        </Card>
      )}
      <Card>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('auth.username')}</th>
                <th>{t('explorer.employee')}</th>
                <th>{t('admin.grants')}</th>
              </tr>
            </thead>
            <tbody>
              {users.data.map((u) => (
                <tr key={u.id}>
                  <td className="mono">{u.username}</td>
                  <td>{pick(u.display_name, u.display_name_ar)}</td>
                  <td>
                    <div className="row" style={{ gap: 6 }}>
                      {u.grants.map((g) => (
                        <span key={g.id} className="badge">
                          {tx('role', g.role)} · {g.scope ? pick(g.scope.name, g.scope.name_ar) : tx('scope', g.scope_type)}
                          {can('admin.manage') && (
                            <button
                              className="btn small ghost danger"
                              style={{ padding: '0 4px' }}
                              aria-label={t('admin.revoke')}
                              onClick={() => call(() => api.del(`/api/admin/users/${u.id}/roles/${g.id}`))}
                            >
                              ×
                            </button>
                          )}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function RolesTab() {
  const { t, tx } = useI18n();
  const { data, error } = useApi<{ permissions: Record<string, string>; roles: { code: string; permissions: string[] }[] }>(
    '/api/admin/roles',
  );
  if (!data) return error ? <ErrorBox error={error} /> : <Loading />;
  const perms = Object.keys(data.permissions);
  return (
    <Card subtitle={t('admin.roleNote')}>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th />
              {data.roles.map((r) => (
                <th key={r.code} style={{ whiteSpace: 'normal', minWidth: 90 }}>
                  {tx('role', r.code)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {perms.map((p) => (
              <tr key={p}>
                <td>
                  <div className="mono">{p}</div>
                  <div className="subtle">{data.permissions[p]}</div>
                </td>
                {data.roles.map((r) => (
                  <td key={r.code} style={{ textAlign: 'center' }}>
                    {r.permissions.includes(p) ? <Badge tone="ok">✓</Badge> : <span className="subtle">·</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function PoliciesTab() {
  const { t, tx, pick, fmtDate } = useI18n();
  const { data, error } = useApi<
    {
      id: string;
      code: string;
      version: string;
      title: string;
      title_ar: string;
      effective_from: string;
      effective_to: string | null;
      rules: { id: string; code: string; version: string; severity: string; description: string; description_ar: string; active: boolean }[];
    }[]
  >('/api/admin/policies');
  if (!data) return error ? <ErrorBox error={error} /> : <Loading />;
  return (
    <Card>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t('case.policy')}</th>
              <th>{t('learning.effective')}</th>
              <th>{t('case.rule')}</th>
            </tr>
          </thead>
          <tbody>
            {data.map((p) => (
              <tr key={p.id}>
                <td>
                  <span className="mono">
                    {p.code} v{p.version}
                  </span>
                  <div>{pick(p.title, p.title_ar)}</div>
                </td>
                <td>
                  {fmtDate(p.effective_from)} → {p.effective_to ? fmtDate(p.effective_to) : '…'}
                </td>
                <td>
                  {p.rules.map((r) => (
                    <div key={r.id} className="row" style={{ gap: 6 }}>
                      <span className="mono">
                        {r.code} v{r.version}
                      </span>
                      <Badge tone={r.active ? 'ok' : 'neutral'}>{tx('severity', r.severity)}</Badge>
                      <span className="subtle">{pick(r.description, r.description_ar)}</span>
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function SourcesTab() {
  const { t } = useI18n();
  const { can } = useAuth();
  const { data, error, reload } = useApi<
    { id: string; code: string; name: string; type: string; owner: string; enabled: boolean; approved_for_use: boolean }[]
  >('/api/admin/source-systems');
  const [actionError, setActionError] = useState<ApiError | null>(null);
  if (!data) return error ? <ErrorBox error={error} /> : <Loading />;
  return (
    <Card>
      <ErrorBox error={actionError} />
      <table>
        <thead>
          <tr>
            <th>{t('case.source')}</th>
            <th>{t('health.owner')}</th>
            <th>{t('admin.approved')}</th>
            <th>{t('admin.enabled')}</th>
          </tr>
        </thead>
        <tbody>
          {data.map((s) => (
            <tr key={s.id}>
              <td>
                {s.name} <span className="mono subtle">{s.code}</span>
              </td>
              <td>{s.owner}</td>
              <td>{s.approved_for_use ? <Badge tone="ok">{t('common.yes')}</Badge> : <Badge tone="warn">{t('common.no')}</Badge>}</td>
              <td>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={s.enabled}
                    disabled={!can('admin.manage')}
                    onChange={async (e) => {
                      setActionError(null);
                      try {
                        await api.patch(`/api/admin/source-systems/${s.id}`, { enabled: e.target.checked });
                        reload();
                      } catch (err) {
                        setActionError(err as ApiError);
                      }
                    }}
                  />
                </label>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function AuditTab() {
  const { t, fmtDate } = useI18n();
  const [page, setPage] = useState(1);
  const [action, setAction] = useState('');
  const { data, error, reload } = useApi<{
    total: number;
    items: {
      id: string;
      occurred_at: string;
      actor: string | null;
      action: string;
      resource_type: string;
      resource_id: string | null;
      outcome: string;
      request_id: string | null;
      metadata: Record<string, unknown>;
    }[];
  }>(`/api/admin/audit-events${qs({ page, page_size: 50, action })}`, 15000);
  return (
    <Card
      actions={
        <select value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }} aria-label={t('admin.action')}>
          <option value="">{t('common.all')}</option>
          {['auth.', 'case.', 'finding.', 'action.', 'learning.', 'simulation.', 'report.', 'pipeline.', 'admin.'].map((a) => (
            <option key={a} value={a}>
              {a}*
            </option>
          ))}
        </select>
      }
    >
      <ErrorBox error={error} onRetry={reload} />
      {!data ? (
        <Loading />
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t('admin.time')}</th>
                  <th>{t('admin.actor')}</th>
                  <th>{t('admin.action')}</th>
                  <th>{t('admin.resource')}</th>
                  <th>{t('admin.outcome')}</th>
                  <th>{t('health.requestId')}</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((e) => (
                  <tr key={e.id}>
                    <td>{fmtDate(e.occurred_at, true)}</td>
                    <td className="mono">{e.actor ?? '—'}</td>
                    <td className="mono">{e.action}</td>
                    <td className="mono subtle">
                      {e.resource_type}
                      {e.resource_id ? `:${e.resource_id}` : ''}
                    </td>
                    <td>
                      <Badge tone={e.outcome === 'success' ? 'ok' : 'bad'}>{e.outcome}</Badge>
                    </td>
                    <td className="mono subtle">{e.request_id ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager page={page} pageSize={50} total={data.total} onPage={setPage} />
        </>
      )}
    </Card>
  );
}

function ConfigTab() {
  const { data, error } = useApi<Record<string, unknown>>('/api/admin/config');
  if (!data) return error ? <ErrorBox error={error} /> : <Loading />;
  return (
    <Card>
      <pre className="mono" style={{ margin: 0, whiteSpace: 'pre-wrap' }} dir="ltr">
        {JSON.stringify(data, null, 2)}
      </pre>
    </Card>
  );
}

export default function AdminPage() {
  const { t } = useI18n();
  const { can } = useAuth();
  const tabs: { id: Tab; label: string; show: boolean }[] = [
    { id: 'users', label: t('admin.users'), show: can('admin.view') },
    { id: 'roles', label: t('admin.roles'), show: can('admin.view') },
    { id: 'policies', label: t('admin.policies'), show: can('admin.view', 'audit.view') },
    { id: 'sources', label: t('admin.sources'), show: can('admin.view') },
    { id: 'audit', label: t('admin.audit'), show: can('audit.view') },
    { id: 'config', label: t('admin.config'), show: can('admin.view') },
  ];
  const visible = tabs.filter((tab) => tab.show);
  const [tab, setTab] = useState<Tab>(visible[0]?.id ?? 'audit');

  return (
    <>
      <PageHead title={t('admin.title')} subtitle={t('admin.subtitle')} />
      <div className="tabs" role="tablist">
        {visible.map((item) => (
          <button key={item.id} role="tab" aria-selected={tab === item.id} className={tab === item.id ? 'active' : ''} onClick={() => setTab(item.id)}>
            {item.label}
          </button>
        ))}
      </div>
      {tab === 'users' && <UsersTab />}
      {tab === 'roles' && <RolesTab />}
      {tab === 'policies' && <PoliciesTab />}
      {tab === 'sources' && <SourcesTab />}
      {tab === 'audit' && <AuditTab />}
      {tab === 'config' && <ConfigTab />}
    </>
  );
}
