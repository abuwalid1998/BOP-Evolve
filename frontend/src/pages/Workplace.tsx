import { useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { api, ApiError, qs } from '../api/client';
import type { UnitRef } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { AiPanel } from '../components/AiPanel';
import { Icon } from '../components/Icon';
import { PageBrief } from '../components/PageBrief';
import { Badge, Bar, Card, Empty, ErrorBox, Field, Kpi, Loading, PageHead, Pager, Toast } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useI18n, type MessageKey } from '../i18n';

// ------------------------------------------------------------------ types
export interface WorkplaceKpis {
  employees?: number;
  scheduled_days: number;
  days_worked: number;
  approved_leave_days: number;
  unapproved_absences: number;
  late_arrivals: number;
  early_departures: number;
  missing_punches: number;
  break_overruns: number;
  punctuality_rate: number | null;
  attendance_rate: number | null;
  unapproved_absence_rate: number | null;
  break_compliance_rate: number | null;
  punch_completeness_rate: number | null;
  avg_break_minutes: number | null;
  avg_minutes_late_when_late: number | null;
  lost_minutes: number;
  lost_hours_per_employee_month: number | null;
  dress_observations: number;
  dress_compliance_rate: number | null;
  adherence_index: number | null;
  exceptions: Record<'open' | 'explained' | 'excused' | 'confirmed' | 'dismissed' | 'total' | 'awaiting_decision', number>;
}

interface Policy {
  id: string;
  code: string;
  version: string;
  title: string;
  title_ar: string;
  summary: string;
  summary_ar: string;
}

interface Overview {
  days: number;
  since: string;
  unit: UnitRef;
  breadcrumb: UnitRef[];
  kpis: WorkplaceKpis;
  children: { unit: UnitRef; kpis: WorkplaceKpis }[];
  weekly: { week: string; punctuality_rate: number | null; break_compliance_rate: number | null; late_arrivals: number; lost_minutes: number; days_worked: number }[];
  weekday: { weekday: string; late_arrivals: number; late_rate: number | null }[];
  by_rule: { rule_code: string; name: string; name_ar: string; category: string; total: number; by_status: Record<string, number> }[];
  reasons: { reason: string; count: number }[];
  attention: { employee_id: string; pseudonym: string; role_title: string; unit: { name: string; name_ar: string } | null; confirmed: number; pending: number }[];
  settings: { grace_minutes: number; break_allowance_minutes: number };
  policies: Policy[];
}

interface Matched {
  label: string;
  label_ar: string;
  actual_label: string | null;
  actual_label_ar: string | null;
}

export interface WorkplaceException {
  id: string;
  occurred_on: string;
  status: 'open' | 'explained' | 'excused' | 'confirmed' | 'dismissed';
  severity: string;
  rule: { id: string; code: string; name: string; name_ar: string; category: string; expected: string; expected_ar: string } | null;
  employee: { id: string; pseudonym: string; role_title: string } | null;
  unit: { id: string; name: string; name_ar: string } | null;
  matched: Matched[];
  record:
    | { type: 'attendance'; status: string; scheduled: string; check_in: string | null; check_out: string | null; minutes_late: number; early_leave_minutes: number; break_minutes: number; break_overrun_minutes: number }
    | { type: 'conduct'; item: string; compliant: boolean; observed_at: string }
    | null;
  reason_code: string | null;
  reason_text: string | null;
  responded_at: string | null;
  decided_at: string | null;
  decided_by: { name: string; name_ar: string } | null;
  decision_note: string | null;
  action: string | null;
  can_respond: boolean;
  can_decide: boolean;
}

interface EmployeeDetail {
  employee: { id: string; pseudonym: string; role_title: string; unit: UnitRef | null; schedule: string; customer_facing: boolean };
  days: number;
  kpis: WorkplaceKpis;
  weekly: Overview['weekly'];
  recent_days: { date: string; status: string; check_in: string | null; check_out: string | null; minutes_late: number; early_leave_minutes: number; break_minutes: number; break_overrun_minutes: number; worked_minutes: number }[];
  exceptions: WorkplaceException[];
  observations: { id: string; item: string; compliant: boolean; observed_at: string }[];
  settings: Overview['settings'];
  policies: Policy[];
}

const REASONS = ['transport', 'family', 'medical', 'time_clock_error', 'approved_by_manager', 'customer_service_overrun', 'other'] as const;
const ACTIONS = ['reminder', 'coaching', 'schedule_review', 'formal_note', 'none'] as const;
const ITEMS = ['formal_attire', 'id_badge', 'uniform', 'grooming'] as const;
const STATUS_TONE: Record<string, 'info' | 'warn' | 'ok' | 'brand' | 'neutral'> = {
  open: 'warn',
  explained: 'info',
  excused: 'ok',
  confirmed: 'brand',
  dismissed: 'neutral',
};

export function ExceptionStatus({ value }: { value: string }) {
  const { tx } = useI18n();
  return <Badge tone={STATUS_TONE[value] ?? 'neutral'}>{tx('wp.status', value)}</Badge>;
}

function indexTone(v: number | null | undefined): 'ok' | 'info' | 'warn' {
  if (v === null || v === undefined) return 'info';
  return v >= 92 ? 'ok' : v >= 85 ? 'info' : 'warn';
}

// --------------------------------------------------------------- charts
function MiniBars({ values, labels, format, title }: { values: (number | null)[]; labels: string[]; format: (v: number | null) => string; title: string }) {
  const max = Math.max(...values.map((v) => v ?? 0), 0.0001);
  return (
    <div className="mini-bars" role="img" aria-label={title}>
      {values.map((v, i) => (
        <div key={labels[i]} className="mini-bar" title={`${labels[i]}: ${format(v)}`}>
          <span style={{ height: `${Math.max(3, ((v ?? 0) / max) * 100)}%` }} />
          <small>{labels[i]}</small>
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------- KPI grid
export function WorkplaceKpiGrid({ k, scope }: { k: WorkplaceKpis; scope: 'unit' | 'person' }) {
  const { t, fmtNumber, fmtPercent } = useI18n();
  return (
    <>
      <div className="grid grid-4" data-tour="wp-kpis">
        <Kpi
          label={t('wp.k.index')}
          value={<Badge tone={indexTone(k.adherence_index)}>{fmtNumber(k.adherence_index, 1)}</Badge>}
          foot={t('wp.k.indexFoot')}
        />
        <Kpi
          label={t('wp.k.punctuality')}
          value={fmtPercent(k.punctuality_rate, 1)}
          foot={t('wp.k.punctualityFoot', { n: fmtNumber(k.late_arrivals), avg: fmtNumber(k.avg_minutes_late_when_late, 0) })}
        />
        <Kpi
          label={t('wp.k.breaks')}
          value={fmtPercent(k.break_compliance_rate, 1)}
          foot={t('wp.k.breaksFoot', { avg: fmtNumber(k.avg_break_minutes, 0), n: fmtNumber(k.break_overruns) })}
        />
        <Kpi
          label={t(scope === 'unit' ? 'wp.k.lost' : 'wp.k.lostPerson')}
          value={fmtNumber(k.lost_hours_per_employee_month, 1)}
          foot={t('wp.k.lostFoot', { h: fmtNumber(k.lost_minutes / 60, 0) })}
        />
      </div>
      <div className="grid grid-4">
        <Kpi
          label={t('wp.k.attendance')}
          value={fmtPercent(k.attendance_rate, 1)}
          foot={t('wp.k.attendanceFoot', { n: fmtNumber(k.unapproved_absences), leave: fmtNumber(k.approved_leave_days) })}
        />
        <Kpi label={t('wp.k.punches')} value={fmtPercent(k.punch_completeness_rate, 1)} foot={t('wp.k.punchesFoot', { n: fmtNumber(k.missing_punches) })} />
        <Kpi label={t('wp.k.dress')} value={fmtPercent(k.dress_compliance_rate, 0)} foot={t('wp.k.dressFoot', { n: fmtNumber(k.dress_observations) })} />
        <Kpi
          label={t('wp.k.awaiting')}
          value={fmtNumber(k.exceptions.awaiting_decision)}
          foot={t('wp.k.awaitingFoot', { c: fmtNumber(k.exceptions.confirmed), e: fmtNumber(k.exceptions.excused) })}
        />
      </div>
    </>
  );
}

function PoliciesCard({ policies, settings }: { policies: Policy[]; settings: Overview['settings'] }) {
  const { t, pick } = useI18n();
  return (
    <Card title={t('wp.policies.title')} subtitle={t('wp.policies.subtitle', { grace: settings.grace_minutes, allowance: settings.break_allowance_minutes })}>
      <div className="grid grid-3">
        {policies.map((p) => (
          <div key={p.id} className="wp-policy">
            <span className="mono subtle">
              {p.code} v{p.version}
            </span>
            <strong>{pick(p.title, p.title_ar)}</strong>
            <p>{pick(p.summary, p.summary_ar)}</p>
          </div>
        ))}
      </div>
    </Card>
  );
}

// -------------------------------------------------------- exception row
function RecordSummary({ x }: { x: WorkplaceException }) {
  const { t, tx, fmtDate } = useI18n();
  const r = x.record;
  if (!r) return null;
  if (r.type === 'conduct') {
    return (
      <span className="subtle">
        {tx('wp.item', r.item)} · {fmtDate(r.observed_at, true)}
      </span>
    );
  }
  if (r.status !== 'worked') return <span className="subtle">{tx('wp.dayStatus', r.status)}</span>;
  return (
    <span className="subtle">
      {t('wp.rec.shift')} <bdi className="mono">{r.scheduled}</bdi> · {t('wp.rec.in')} <bdi className="mono">{r.check_in ?? '—'}</bdi> ·{' '}
      {t('wp.rec.out')} <bdi className="mono">{r.check_out ?? '—'}</bdi> · {t('wp.rec.break')} <bdi>{t('wp.trend.minutes', { m: r.break_minutes })}</bdi>
    </span>
  );
}

function RespondForm({ x, onDone }: { x: WorkplaceException; onDone: () => void }) {
  const { t, tx } = useI18n();
  const [reason, setReason] = useState<string>('transport');
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/workplace/exceptions/${x.id}/respond`, { reason_code: reason, reason_text: text || null });
      onDone();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="wp-respond">
      <Field label={t('wp.respond.reason')}>
        <select value={reason} onChange={(e) => setReason(e.target.value)}>
          {REASONS.map((r) => (
            <option key={r} value={r}>
              {tx('wp.reason', r)}
            </option>
          ))}
        </select>
      </Field>
      <Field label={t('wp.respond.text')} help={t('wp.respond.help')}>
        <textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={500} rows={2} />
      </Field>
      <button className="btn small primary" disabled={busy} onClick={submit}>
        {t('wp.respond.submit')}
      </button>
      <ErrorBox error={error} />
    </div>
  );
}

function DecideForm({ x, onDone }: { x: WorkplaceException; onDone: () => void }) {
  const { t, tx } = useI18n();
  const [action, setAction] = useState<string>('reminder');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const decide = async (decision: 'excused' | 'confirmed' | 'dismissed') => {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/workplace/exceptions/${x.id}/decide`, {
        decision,
        action: decision === 'confirmed' ? action : null,
        note: note || null,
      });
      onDone();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="wp-decide">
      <input placeholder={t('wp.decide.note')} value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
      <select value={action} onChange={(e) => setAction(e.target.value)} aria-label={t('wp.decide.action')}>
        {ACTIONS.map((a) => (
          <option key={a} value={a}>
            {tx('wp.action', a)}
          </option>
        ))}
      </select>
      <button className="btn small primary" disabled={busy} onClick={() => decide('confirmed')}>
        {t('wp.decide.confirm')}
      </button>
      <button className="btn small" disabled={busy} onClick={() => decide('excused')}>
        {t('wp.decide.excuse')}
      </button>
      <button className="btn small ghost" disabled={busy} onClick={() => decide('dismissed')}>
        {t('wp.decide.dismiss')}
      </button>
      <ErrorBox error={error} />
    </div>
  );
}

export function ExceptionItem({ x, onChange, showEmployee = true }: { x: WorkplaceException; onChange: () => void; showEmployee?: boolean }) {
  const { t, tx, pick, fmtDate } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <li className="wp-exception">
      <div className="row between" style={{ alignItems: 'flex-start' }}>
        <div className="stack" style={{ gap: 4 }}>
          <div className="row" style={{ gap: 8 }}>
            <strong>{x.rule ? pick(x.rule.name, x.rule.name_ar) : '—'}</strong>
            <ExceptionStatus value={x.status} />
            <Badge tone={x.severity === 'high' ? 'warn' : 'neutral'}>{tx('severity', x.severity)}</Badge>
          </div>
          <span className="subtle">
            {fmtDate(x.occurred_on)}
            {showEmployee && x.employee && (
              <>
                {' · '}
                <Link to={`/workplace/employees/${x.employee.id}`} className="mono">
                  {x.employee.pseudonym}
                </Link>{' '}
                {x.unit && `· ${pick(x.unit.name, x.unit.name_ar)}`}
              </>
            )}
          </span>
          <RecordSummary x={x} />
          {x.matched.length > 0 && (
            <span className="subtle">
              {x.matched.map((m) => `${pick(m.label, m.label_ar)}: ${pick(m.actual_label, m.actual_label_ar) || '—'}`).join(' · ')}
            </span>
          )}
          {x.reason_code && (
            <span>
              <Icon name="info" size={13} /> {t('wp.reasonGiven')}: <strong>{tx('wp.reason', x.reason_code)}</strong>
              {x.reason_text && <span className="subtle"> — “{x.reason_text}”</span>}
            </span>
          )}
          {x.decided_at && (
            <span className="subtle">
              {t('wp.decidedBy', { who: x.decided_by ? pick(x.decided_by.name, x.decided_by.name_ar) : '—', date: fmtDate(x.decided_at) })}
              {x.action && ` · ${tx('wp.action', x.action)}`}
              {x.decision_note && ` · “${x.decision_note}”`}
            </span>
          )}
        </div>
        {(x.can_respond || x.can_decide) && (
          <button className="btn small" onClick={() => setOpen(!open)} aria-expanded={open}>
            {x.can_respond ? t('wp.respond.open') : t('wp.decide.open')}
          </button>
        )}
      </div>
      {open && x.can_respond && <RespondForm x={x} onDone={onChange} />}
      {open && x.can_decide && <DecideForm x={x} onDone={onChange} />}
    </li>
  );
}

// ------------------------------------------------------------ overview tab
function OverviewTab() {
  const { t, tx, pick, fmtNumber, fmtPercent, fmtDate } = useI18n();
  const [params, setParams] = useSearchParams();
  const unitId = params.get('unit') ?? '';
  const [days, setDays] = useState(30);
  const { data, error, loading, reload } = useApi<Overview>(`/api/workplace/overview${qs({ unit_id: unitId, days })}`);
  const pickUnit = (id: string | null) => setParams(id ? { unit: id } : {});

  if (!data) return loading ? <Loading /> : <ErrorBox error={error} onRetry={reload} />;
  const k = data.kpis;
  const maxLost = Math.max(...data.children.map((c) => c.kpis.lost_hours_per_employee_month ?? 0), 0.1);
  const reasonMax = Math.max(...data.reasons.map((r) => r.count), 1);

  return (
    <div className="stack">
      <div className="row between">
        <nav className="wf-breadcrumb" aria-label={t('wf.breadcrumb')}>
          {data.breadcrumb.map((u, i) => (
            <span key={u.id}>
              {i > 0 && <span className="subtle"> › </span>}
              {i === data.breadcrumb.length - 1 ? (
                <strong>{pick(u.name, u.name_ar)}</strong>
              ) : (
                <button className="linklike" onClick={() => pickUnit(u.type === 'bank' ? null : u.id)}>
                  {pick(u.name, u.name_ar)}
                </button>
              )}
            </span>
          ))}
        </nav>
        <div className="segmented" role="group" aria-label={t('wp.period')}>
          {[30, 60, 90].map((d) => (
            <button key={d} className={days === d ? 'active' : ''} aria-pressed={days === d} onClick={() => setDays(d)}>
              {t('wp.days', { n: d })}
            </button>
          ))}
        </div>
      </div>
      <p className="subtle" style={{ margin: 0 }}>
        {t('wp.periodNote', { since: fmtDate(data.since), n: fmtNumber(k.employees ?? 0), days: fmtNumber(k.days_worked) })}
      </p>
      <WorkplaceKpiGrid k={k} scope="unit" />

      <AiPanel
        feature="workplace_insights"
        title={t('wp.ai.title')}
        intro={t('wp.ai.intro')}
        endpoint="/api/ai/workplace/insights"
        body={{ unit_id: unitId || null, days }}
        keys={['headline', 'patterns', 'likely_causes', 'recommendations', 'caution']}
        tour="wp-ai"
      />

      {data.children.length > 0 && (
        <Card title={t('wp.units.title')} subtitle={t('wp.units.subtitle')}>
          <div className="table-wrap" data-tour="wp-units">
            <table>
              <thead>
                <tr>
                  <th>{t('explorer.unit')}</th>
                  <th className="num">{t('wf.k.employees')}</th>
                  <th>{t('wp.k.index')}</th>
                  <th className="num">{t('wp.k.punctuality')}</th>
                  <th className="num">{t('wp.k.breaks')}</th>
                  <th className="num">{t('wp.col.absence')}</th>
                  <th className="num">{t('wp.k.dress')}</th>
                  <th>{t('wp.k.lost')}</th>
                  <th className="num">{t('wp.k.awaiting')}</th>
                </tr>
              </thead>
              <tbody>
                {data.children.map((c) => (
                  <tr key={c.unit.id} className="clickable" onClick={() => pickUnit(c.unit.id)}>
                    <td>
                      <strong>{pick(c.unit.name, c.unit.name_ar)}</strong>
                      <div className="subtle">{tx('level', c.unit.type)}</div>
                    </td>
                    <td className="num">{fmtNumber(c.kpis.employees)}</td>
                    <td>
                      <Badge tone={indexTone(c.kpis.adherence_index)}>{fmtNumber(c.kpis.adherence_index, 1)}</Badge>
                    </td>
                    <td className="num">{fmtPercent(c.kpis.punctuality_rate, 1)}</td>
                    <td className="num">{fmtPercent(c.kpis.break_compliance_rate, 1)}</td>
                    <td className="num">{fmtPercent(c.kpis.unapproved_absence_rate, 1)}</td>
                    <td className="num">{fmtPercent(c.kpis.dress_compliance_rate, 0)}</td>
                    <td style={{ minWidth: 120 }}>
                      {fmtNumber(c.kpis.lost_hours_per_employee_month, 1)}
                      <Bar value={(c.kpis.lost_hours_per_employee_month ?? 0) / maxLost} />
                    </td>
                    <td className="num">
                      {c.kpis.exceptions.awaiting_decision > 0 ? <Badge tone="warn">{c.kpis.exceptions.awaiting_decision}</Badge> : '0'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <div className="grid grid-2">
        <Card title={t('wp.trend.title')} subtitle={t('wp.trend.subtitle')}>
          {data.weekly.length ? (
            <MiniBars
              title={t('wp.trend.title')}
              values={data.weekly.map((w) => (w.days_worked ? w.lost_minutes / w.days_worked : null))}
              labels={data.weekly.map((w) => fmtDate(w.week).replace(/\s\d{4}$/, ''))}
              format={(v) => t('wp.trend.value', { m: fmtNumber(v, 1) })}
            />
          ) : (
            <Empty />
          )}
        </Card>
        <Card title={t('wp.weekday.title')} subtitle={t('wp.weekday.subtitle')}>
          {data.weekday.length ? (
            <MiniBars
              title={t('wp.weekday.title')}
              values={data.weekday.map((w) => w.late_rate)}
              labels={data.weekday.map((w) => tx('weekday', w.weekday))}
              format={(v) => fmtPercent(v, 1)}
            />
          ) : (
            <Empty />
          )}
        </Card>
      </div>

      <div className="grid grid-2">
        <Card title={t('wp.rules.title')} subtitle={t('wp.rules.subtitle')}>
          {data.by_rule.length === 0 ? (
            <Empty />
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{t('wp.rules.rule')}</th>
                    <th className="num">{t('wp.rules.total')}</th>
                    <th className="num">{tx('wp.status', 'confirmed')}</th>
                    <th className="num">{tx('wp.status', 'excused')}</th>
                    <th className="num">{t('wp.k.awaiting')}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_rule.map((r) => (
                    <tr key={r.rule_code}>
                      <td>
                        {pick(r.name, r.name_ar)}
                        <div className="subtle mono">{r.rule_code}</div>
                      </td>
                      <td className="num">{fmtNumber(r.total)}</td>
                      <td className="num">{fmtNumber(r.by_status.confirmed ?? 0)}</td>
                      <td className="num">{fmtNumber(r.by_status.excused ?? 0)}</td>
                      <td className="num">{fmtNumber((r.by_status.open ?? 0) + (r.by_status.explained ?? 0))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <Card title={t('wp.reasons.title')} subtitle={t('wp.reasons.subtitle')}>
          {data.reasons.length === 0 ? (
            <Empty />
          ) : (
            <ul className="wp-reasons">
              {data.reasons.map((r) => (
                <li key={r.reason}>
                  <span>{tx('wp.reason', r.reason)}</span>
                  <Bar value={r.count / reasonMax} />
                  <span className="num">{fmtNumber(r.count)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title={t('wp.attention.title')} subtitle={t('wp.attention.subtitle')}>
        {data.attention.length === 0 ? (
          <Empty>{t('wp.attention.none')}</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t('explorer.employee')}</th>
                  <th>{t('explorer.unit')}</th>
                  <th className="num">{tx('wp.status', 'confirmed')}</th>
                  <th className="num">{t('wp.k.awaiting')}</th>
                </tr>
              </thead>
              <tbody>
                {data.attention.map((a) => (
                  <tr key={a.employee_id}>
                    <td>
                      <Link className="mono" to={`/workplace/employees/${a.employee_id}`}>
                        {a.pseudonym}
                      </Link>
                      <div className="subtle">{a.role_title}</div>
                    </td>
                    <td>{a.unit ? pick(a.unit.name, a.unit.name_ar) : '—'}</td>
                    <td className="num">{fmtNumber(a.confirmed)}</td>
                    <td className="num">{fmtNumber(a.pending)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <PoliciesCard policies={data.policies} settings={data.settings} />
    </div>
  );
}

// ---------------------------------------------------------- decisions tab
function DecisionsTab() {
  const { t, tx } = useI18n();
  const [status, setStatus] = useState('pending');
  const [category, setCategory] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulk, setBulk] = useState<{ decision: string; action: string }>({ decision: 'excused', action: 'reminder' });
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const data = useApi<{ total: number; page: number; page_size: number; items: WorkplaceException[] }>(
    `/api/workplace/exceptions${qs({ status, category, page, page_size: 25 })}`,
  );
  const items = data.data?.items ?? [];
  const decidable = items.filter((x) => x.can_decide);
  const toggle = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };
  const applyBulk = async () => {
    setError(null);
    try {
      const r = await api.post<{ decided: number; skipped: unknown[] }>('/api/workplace/exceptions/decide-bulk', {
        ids: [...selected],
        decision: bulk.decision,
        action: bulk.decision === 'confirmed' ? bulk.action : null,
      });
      setSelected(new Set());
      setToast(t('wp.bulk.done', { n: r.decided }));
      setTimeout(() => setToast(null), 2500);
      data.reload();
    } catch (err) {
      setError(err as ApiError);
    }
  };

  return (
    <Card
      title={t('wp.queue.title')}
      subtitle={t('wp.queue.subtitle')}
      actions={
        <>
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label={t('wp.queue.status')}>
            {['pending', 'open', 'explained', 'confirmed', 'excused', 'dismissed', ''].map((s) => (
              <option key={s || 'all'} value={s}>
                {s ? tx('wp.status', s) : t('common.all')}
              </option>
            ))}
          </select>
          <select value={category} onChange={(e) => { setCategory(e.target.value); setPage(1); }} aria-label={t('wp.queue.category')}>
            <option value="">{t('common.all')}</option>
            <option value="attendance">{tx('caseType', 'attendance')}</option>
            <option value="dress_code">{tx('caseType', 'dress_code')}</option>
          </select>
        </>
      }
    >
      {decidable.length > 0 && (
        <div className="wp-bulk" data-tour="wp-bulk">
          <label className="row" style={{ gap: 6 }}>
            <input
              type="checkbox"
              checked={decidable.every((x) => selected.has(x.id))}
              onChange={(e) => setSelected(e.target.checked ? new Set(decidable.map((x) => x.id)) : new Set())}
            />
            {t('wp.bulk.selectPage')}
          </label>
          <span className="subtle">{t('wp.bulk.selected', { n: selected.size })}</span>
          <div className="spacer" />
          <select value={bulk.decision} onChange={(e) => setBulk({ ...bulk, decision: e.target.value })} aria-label={t('wp.bulk.decision')}>
            {['excused', 'confirmed', 'dismissed'].map((d) => (
              <option key={d} value={d}>
                {tx('wp.status', d)}
              </option>
            ))}
          </select>
          {bulk.decision === 'confirmed' && (
            <select value={bulk.action} onChange={(e) => setBulk({ ...bulk, action: e.target.value })} aria-label={t('wp.decide.action')}>
              {ACTIONS.map((a) => (
                <option key={a} value={a}>
                  {tx('wp.action', a)}
                </option>
              ))}
            </select>
          )}
          <button className="btn small primary" disabled={selected.size === 0} onClick={applyBulk}>
            {t('wp.bulk.apply')}
          </button>
        </div>
      )}
      <ErrorBox error={error ?? data.error} onRetry={data.reload} />
      {!data.data && data.loading && <Loading />}
      {data.data && items.length === 0 && <Empty>{t('wp.queue.empty')}</Empty>}
      <ul className="wp-list">
        {items.map((x) => (
          <div key={x.id} className="wp-select-row">
            {x.can_decide && (
              <input type="checkbox" checked={selected.has(x.id)} onChange={() => toggle(x.id)} aria-label={t('wp.bulk.select')} />
            )}
            <ExceptionItem x={x} onChange={data.reload} />
          </div>
        ))}
      </ul>
      {data.data && data.data.total > data.data.page_size && (
        <Pager page={page} pageSize={data.data.page_size} total={data.data.total} onPage={setPage} />
      )}
      <Toast message={toast} />
    </Card>
  );
}

// -------------------------------------------------------- observation tab
function ObserveTab() {
  const { t, tx } = useI18n();
  const [q, setQ] = useState('');
  const staff = useApi<{ id: string; pseudonym: string; role_title: string }[]>(`/api/workplace/employees${qs({ q })}`);
  const [employee, setEmployee] = useState('');
  const [item, setItem] = useState<string>('formal_attire');
  const [compliant, setCompliant] = useState(true);
  const [note, setNote] = useState('');
  const [result, setResult] = useState<{ id: string; exceptions: WorkplaceException[] } | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.post('/api/workplace/observations', { employee_id: employee, item, compliant, note: note || null }));
      setNote('');
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title={t('wp.observe.title')} subtitle={t('wp.observe.subtitle')}>
      <div className="grid grid-2">
        <div className="stack" style={{ gap: 10 }}>
          <Field label={t('wp.observe.search')}>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="E-…" dir="ltr" />
          </Field>
          <Field label={t('explorer.employee')}>
            <select value={employee} onChange={(e) => setEmployee(e.target.value)} size={6}>
              {(staff.data ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.pseudonym} · {s.role_title}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="stack" style={{ gap: 10 }}>
          <Field label={t('wp.observe.item')}>
            <select value={item} onChange={(e) => setItem(e.target.value)}>
              {ITEMS.map((i) => (
                <option key={i} value={i}>
                  {tx('wp.item', i)}
                </option>
              ))}
            </select>
          </Field>
          <div className="segmented" role="group" aria-label={t('wp.observe.result')}>
            <button className={compliant ? 'active' : ''} aria-pressed={compliant} onClick={() => setCompliant(true)}>
              <Icon name="check" size={14} /> {t('wp.observe.met')}
            </button>
            <button className={!compliant ? 'active' : ''} aria-pressed={!compliant} onClick={() => setCompliant(false)}>
              <Icon name="cross" size={14} /> {t('wp.observe.notMet')}
            </button>
          </div>
          <Field label={t('wp.observe.note')} help={t('wp.observe.noteHelp')}>
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} />
          </Field>
          <button className="btn primary" disabled={!employee || busy} onClick={submit}>
            {t('wp.observe.submit')}
          </button>
          <ErrorBox error={error} />
          {result && (
            <div className={`callout ${result.exceptions.length ? 'info' : 'brand'}`}>
              {result.exceptions.length ? t('wp.observe.raised') : t('wp.observe.recorded')}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

// -------------------------------------------------------- employee view
export function EmployeeWorkplace({ path, mine = false }: { path: string; mine?: boolean }) {
  const { t, tx, pick, fmtDate, fmtNumber } = useI18n();
  const { data, error, loading, reload } = useApi<EmployeeDetail>(path);
  const [showAll, setShowAll] = useState(false);
  if (!data) return loading ? <Loading /> : <ErrorBox error={error} onRetry={reload} />;
  const open = data.exceptions.filter((x) => x.status === 'open' || x.status === 'explained');
  const listed = showAll ? data.exceptions : data.exceptions.slice(0, 12);
  return (
    <div className="stack">
      <Card>
        <div className="row between">
          <div>
            <strong className="mono">{data.employee.pseudonym}</strong> · {data.employee.role_title}
            <div className="subtle">
              {data.employee.unit ? pick(data.employee.unit.name, data.employee.unit.name_ar) : '—'} · {t('wp.schedule')}{' '}
              <span dir="ltr">{data.employee.schedule}</span>
            </div>
          </div>
          {open.length > 0 && <Badge tone="warn">{t(mine ? 'wp.me.pending' : 'wp.emp.pending', { n: open.length })}</Badge>}
        </div>
      </Card>
      <WorkplaceKpiGrid k={data.kpis} scope="person" />
      <Card title={t(mine ? 'wp.me.exceptions' : 'wp.emp.exceptions')} subtitle={t(mine ? 'wp.me.exceptionsSub' : 'wp.emp.exceptionsSub')}>
        {data.exceptions.length === 0 ? (
          <Empty>{t('wp.me.none')}</Empty>
        ) : (
          <>
            <ul className="wp-list">
              {listed.map((x) => (
                <ExceptionItem key={x.id} x={x} onChange={reload} showEmployee={false} />
              ))}
            </ul>
            {data.exceptions.length > listed.length && (
              <button className="btn small ghost" onClick={() => setShowAll(true)}>
                {t('wp.showAll', { n: data.exceptions.length })}
              </button>
            )}
          </>
        )}
      </Card>
      <Card title={t('wp.days.title')} subtitle={t('wp.days.subtitle')}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('wp.days.date')}</th>
                <th>{t('wp.days.status')}</th>
                <th>{t('wp.rec.in')}</th>
                <th>{t('wp.rec.out')}</th>
                <th className="num">{t('wp.days.late')}</th>
                <th className="num">{t('wp.days.break')}</th>
                <th className="num">{t('wp.days.worked')}</th>
              </tr>
            </thead>
            <tbody>
              {data.recent_days.map((d) => (
                <tr key={d.date}>
                  <td>{fmtDate(d.date)}</td>
                  <td>{d.status === 'worked' ? '' : <Badge tone={d.status === 'approved_leave' ? 'neutral' : 'warn'}>{tx('wp.dayStatus', d.status)}</Badge>}</td>
                  <td className="mono">{d.status === 'worked' ? (d.check_in ?? <Badge tone="warn">{t('wp.missing')}</Badge>) : '—'}</td>
                  <td className="mono">{d.status === 'worked' ? (d.check_out ?? <Badge tone="warn">{t('wp.missing')}</Badge>) : '—'}</td>
                  <td className="num">{d.minutes_late > data.settings.grace_minutes ? <strong>{d.minutes_late}</strong> : d.minutes_late || '—'}</td>
                  <td className="num">
                    {d.status === 'worked' ? (d.break_overrun_minutes > 0 ? <strong>{d.break_minutes}</strong> : d.break_minutes) : '—'}
                  </td>
                  <td className="num">{d.worked_minutes ? fmtNumber(d.worked_minutes / 60, 1) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {data.observations.length > 0 && (
        <Card title={t('wp.obs.title')}>
          <ul className="wp-obs">
            {data.observations.map((o) => (
              <li key={o.id}>
                <Badge tone={o.compliant ? 'ok' : 'warn'}>{o.compliant ? t('wp.observe.met') : t('wp.observe.notMet')}</Badge> {tx('wp.item', o.item)} ·{' '}
                <span className="subtle">{fmtDate(o.observed_at)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <PoliciesCard policies={data.policies} settings={data.settings} />
    </div>
  );
}

export function WorkplaceEmployeePage() {
  const { employeeId } = useParams();
  const { t } = useI18n();
  return (
    <>
      <PageHead
        title={t('wp.emp.title')}
        subtitle={t('wp.emp.subtitle')}
        actions={
          <Link to="/workplace" className="btn small">
            {t('common.back')}
          </Link>
        }
      />
      <EmployeeWorkplace path={`/api/workplace/employees/${employeeId}?days=90`} />
    </>
  );
}

// ------------------------------------------------------------------ page
type Tab = 'overview' | 'decisions' | 'observe' | 'mine';

export default function WorkplacePage() {
  const { t } = useI18n();
  const { user, can } = useAuth();
  // Staff with only self-service access see their own record; managers and HR see their units.
  const selfOnly = !!user && user.roles.every((r) => r.scope_type === 'self');
  const tabs = useMemo(() => {
    const list: Tab[] = [];
    if (!selfOnly) list.push('overview');
    if (can('workplace.review')) list.push('decisions');
    if (can('workplace.observe')) list.push('observe');
    if (user?.employee_id) list.push('mine');
    return list;
  }, [selfOnly, can, user]);
  const [tab, setTab] = useState<Tab>(tabs[0] ?? 'mine');

  return (
    <>
      <PageHead title={t(selfOnly ? 'wp.me.title' : 'wp.title')} subtitle={t(selfOnly ? 'wp.me.subtitle' : 'wp.subtitle')} />
      <PageBrief page="workplace" />
      {tabs.length > 1 && (
        <div className="tabs" role="tablist" data-tour="wp-tabs">
          {tabs.map((id) => (
            <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
              {t(`wp.tab.${id}` as MessageKey)}
            </button>
          ))}
        </div>
      )}
      {tab === 'overview' && <OverviewTab />}
      {tab === 'decisions' && <DecisionsTab />}
      {tab === 'observe' && <ObserveTab />}
      {tab === 'mine' && <EmployeeWorkplace path="/api/workplace/me?days=90" mine />}
    </>
  );
}

