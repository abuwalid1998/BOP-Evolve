import { useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Bar as RBar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../api/client';
import type { UnitRef } from '../api/types';
import logo from '../assets/logo.png';
import { GenBadge, GenerationTrack } from '../components/GenerationTrack';
import { Icon } from '../components/Icon';
import { PageBrief } from '../components/PageBrief';
import { Badge, Card, Empty, ErrorBox, Kpi, Loading, StatusBadge } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useI18n, type MessageKey } from '../i18n';
import { OutlookBadge, type EmployeeSummary, type ModelInfo, type OutlookItem } from './Workforce';

interface Person {
  id: string;
  name: string;
  name_ar: string;
  role: string | null;
}

interface TimelineItem {
  finding_id: string;
  case_id: string;
  occurred_at: string;
  case_type: string;
  rule: { code: string; version: string; name: string; name_ar: string } | null;
  severity: string;
  status: string;
  observed: string;
  observed_ar: string;
  awareness: string | null;
  understood: boolean | null;
  decision: { decision: string; by: Person | null; at: string; factor: string } | null;
  actions: {
    type: string;
    description: string;
    owner: Person | null;
    agreed_by: Person | null;
    status: string;
    due_at: string | null;
    completed_at: string | null;
    on_time: boolean;
    overdue: boolean;
  }[];
  coaching: { at: string; outcome: string; by: Person | null }[];
  follow_up: { comparable: number; recurrences: number; recurred: boolean } | null;
}

interface Report {
  generated_at: string;
  generated_by: { name: string; name_ar: string | null };
  employee: { id: string; pseudonym: string; role_title: string; start_date: string | null; path: UnitRef[] };
  summary: EmployeeSummary;
  stages: { code: string; status: string; effective_at: string; approved_by: Person | null; score: number | null }[];
  timeline: TimelineItem[];
  monthly: { month: string; cases: number; confirmed: number; findings: number }[];
  by_type: {
    case_type: string;
    cases: number;
    findings: number;
    confirmed: number;
    rate_per_100: number | null;
    last_at: string | null;
    learning_rate: number | null;
  }[];
  model: ModelInfo;
}

function useWho() {
  const { pick, tx } = useI18n();
  return (p: Person | null) => (p ? `${pick(p.name, p.name_ar)}${p.role ? ` (${tx('role', p.role)})` : ''}` : '—');
}

function driverText(t: (k: MessageKey, v?: Record<string, string | number>) => string, d: OutlookItem['drivers'][number]) {
  return t(`driver.${d.code}` as MessageKey, { n: d.n ?? 0, ratio: d.ratio ?? 1 });
}

export default function EmployeeReportPage() {
  const { employeeId } = useParams();
  const { t, tx, pick, fmtNumber, fmtPercent, fmtDate, lang, dir } = useI18n();
  const who = useWho();
  const { data, error, loading, reload } = useApi<Report>(`/api/hr/employees/${employeeId}/report`);
  const month = useMemo(
    () => new Intl.DateTimeFormat(lang === 'ar' ? 'ar-PS-u-nu-latn' : 'en-GB', { month: 'short', year: '2-digit' }),
    [lang],
  );

  if (!data) return loading ? <Loading /> : <ErrorBox error={error} onRetry={reload} />;
  const { employee, summary: s } = data;
  const gapsByType = s.knowledge_gaps.reduce<Record<string, typeof s.knowledge_gaps>>((acc, g) => {
    (acc[g.case_type] ??= []).push(g);
    return acc;
  }, {});

  const print = async () => {
    try {
      await api.post(`/api/hr/employees/${employee.id}/report/printed`);
    } catch {
      /* printing still works; the audit call is best effort */
    }
    window.print();
  };

  return (
    <div className="emp-report">
      <div className="row between no-print" style={{ marginBottom: 12 }}>
        <Link className="btn small" to="/workforce">
          {t('common.back')}
        </Link>
        <button className="btn primary" onClick={print} data-tour="report-print">
          <Icon name="download" size={16} /> {t('emp.print')}
        </button>
      </div>
      <div className="no-print">
        <PageBrief page="report" />
      </div>

      <header className="emp-report-head" data-tour="report-head">
        <img src={logo} alt="" width={56} height={56} />
        <div>
          <div className="subtle">{t('emp.title')}</div>
          <h1>
            {employee.pseudonym} · {employee.role_title}
          </h1>
          <div className="subtle">
            {employee.path.map((u) => pick(u.name, u.name_ar)).join(' › ')}
            {employee.start_date && ` · ${t('emp.since', { date: fmtDate(employee.start_date) })}`}
          </div>
        </div>
        <div className="emp-report-meta">
          <div>{t('emp.generated', { date: fmtDate(data.generated_at, true) })}</div>
          <div>{t('emp.generatedBy', { name: pick(data.generated_by.name, data.generated_by.name_ar) })}</div>
          <Badge tone="warn">{t('emp.confidential')}</Badge>
        </div>
      </header>

      <div className="stack">
        <div className="grid grid-4" data-tour="report-kpis">
          <Kpi
            label={t('emp.k.mistakes')}
            value={fmtNumber(s.confirmed_12m)}
            foot={t('emp.k.mistakesFoot', {
              total: fmtNumber(s.findings_12m),
              pending: fmtNumber(s.pending_review),
              rate: fmtNumber(s.rate_per_100, 2),
            })}
          />
          <Kpi label={t('emp.k.repeats')} value={fmtNumber(s.repeats)} foot={t('emp.k.repeatsFoot')} />
          <Kpi
            label={t('emp.k.learning')}
            value={fmtPercent(s.learning_rate)}
            foot={t('emp.k.learningFoot', { n: fmtNumber(s.follow_ups_evaluated) })}
          />
          <Kpi
            label={t('emp.k.actions')}
            value={`${fmtNumber(s.actions.completed)} / ${fmtNumber(s.actions.total)}`}
            foot={t('emp.k.actionsFoot', {
              ontime: fmtPercent(s.actions.on_time_rate),
              overdue: fmtNumber(s.actions.overdue),
            })}
          />
        </div>

        <Card title={t('emp.stage.title')} subtitle={t('learning.metaphor')}>
          <div data-tour="report-stage">
            <GenerationTrack current={s.stage} />
          </div>
          <ul className="emp-stage-history">
            {data.stages.map((g, i) => (
              <li key={i}>
                <GenBadge code={g.code} /> <StatusBadge prefix="genStatus" value={g.status} />{' '}
                <span className="subtle">
                  {fmtDate(g.effective_at)}
                  {g.approved_by && ` · ${t('emp.stage.approvedBy', { name: who(g.approved_by) })}`}
                </span>
              </li>
            ))}
          </ul>
        </Card>

        <div className="grid grid-2 emp-print-stack">
          <Card title={t('emp.trend.title')} subtitle={t('emp.trend.subtitle')}>
            <div style={{ height: 220 }} dir="ltr" data-tour="report-trend" className="no-break">
              <ResponsiveContainer>
                <BarChart data={data.monthly} margin={{ top: 6, right: 8, bottom: 0, left: -18 }}>
                  <CartesianGrid stroke="var(--border)" vertical={false} />
                  <XAxis
                    dataKey="month"
                    tickFormatter={(v: string) => month.format(new Date(`${v}-01T00:00:00Z`))}
                    tick={{ fontSize: 10, fill: 'var(--text-3)' }}
                    reversed={dir === 'rtl'}
                  />
                  <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: 'var(--text-3)' }} orientation={dir === 'rtl' ? 'right' : 'left'} />
                  <Tooltip
                    contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10 }}
                    labelFormatter={(v: string) => month.format(new Date(`${v}-01T00:00:00Z`))}
                  />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <RBar dataKey="findings" name={t('emp.trend.raised')} fill="var(--border-strong)" isAnimationActive={false} />
                  <RBar dataKey="confirmed" name={t('emp.trend.confirmed')} fill="var(--brand)" isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
          <Card title={t('emp.types.title')} subtitle={t('emp.types.subtitle')}>
            <div className="table-wrap" data-tour="report-types">
              <table>
                <thead>
                  <tr>
                    <th>{t('explorer.category')}</th>
                    <th className="num">{t('emp.types.cases')}</th>
                    <th className="num">{t('emp.types.confirmed')}</th>
                    <th className="num">{t('insights.rate')}</th>
                    <th>{t('emp.types.last')}</th>
                    <th className="num">{t('emp.k.learning')}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_type.map((r) => (
                    <tr key={r.case_type}>
                      <td>{tx('caseType', r.case_type)}</td>
                      <td className="num">{fmtNumber(r.cases)}</td>
                      <td className="num">{fmtNumber(r.confirmed)}</td>
                      <td className="num">{fmtNumber(r.rate_per_100, 2)}</td>
                      <td>{r.last_at ? fmtDate(r.last_at) : '—'}</td>
                      <td className="num">{fmtPercent(r.learning_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>

        <Card title={t('emp.timeline.title')} subtitle={t('emp.timeline.subtitle')}>
          {data.timeline.length === 0 ? (
            <Empty>{t('emp.timeline.empty')}</Empty>
          ) : (
            <div className="table-wrap" data-tour="report-timeline">
              <table className="emp-timeline">
                <thead>
                  <tr>
                    <th>{t('emp.timeline.when')}</th>
                    <th>{t('emp.timeline.what')}</th>
                    <th>{t('emp.timeline.account')}</th>
                    <th>{t('emp.timeline.decision')}</th>
                    <th>{t('emp.timeline.actions')}</th>
                    <th>{t('emp.timeline.followUp')}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.timeline.map((f) => (
                    <tr key={f.finding_id}>
                      <td>
                        <strong>{fmtDate(f.occurred_at)}</strong>
                        <div>
                          <Link className="mono no-print-link" to={`/cases/${f.case_id}`}>
                            {f.case_id}
                          </Link>
                        </div>
                      </td>
                      <td>
                        <div>{tx('caseType', f.case_type)}</div>
                        {f.rule && <div className="subtle">{pick(f.rule.name, f.rule.name_ar) || f.rule.code}</div>}
                        <div className="row" style={{ gap: 4, marginTop: 4 }}>
                          <StatusBadge prefix="status" value={f.status} />
                          <StatusBadge prefix="severity" value={f.severity} />
                        </div>
                      </td>
                      <td>
                        {f.awareness ? tx('awareness', f.awareness) : <span className="subtle">{t('case.notYet')}</span>}
                        {f.understood !== null && (
                          <div className="subtle">{t(f.understood ? 'case.understoodYes' : 'case.understoodNo')}</div>
                        )}
                      </td>
                      <td>
                        {f.decision ? (
                          <>
                            <strong>{tx('decision', f.decision.decision)}</strong>
                            <div className="subtle">
                              {who(f.decision.by)} · {fmtDate(f.decision.at)}
                            </div>
                            {f.decision.factor !== 'undetermined' && (
                              <div className="subtle">
                                {t('emp.timeline.rootCause')}: {tx('factor', f.decision.factor)}
                              </div>
                            )}
                          </>
                        ) : (
                          <span className="subtle">{t('status.POTENTIAL')}</span>
                        )}
                      </td>
                      <td>
                        {f.actions.length === 0 && f.coaching.length === 0 && <span className="subtle">—</span>}
                        <ul className="emp-actions">
                          {f.actions.map((a, i) => (
                            <li key={i}>
                              <strong>{tx('actionType', a.type)}</strong> · {who(a.owner)}
                              <div className="subtle">
                                {a.completed_at
                                  ? t(a.on_time ? 'emp.action.doneOnTime' : 'emp.action.doneLate', { date: fmtDate(a.completed_at) })
                                  : a.overdue
                                    ? t('emp.action.overdue', { date: fmtDate(a.due_at) })
                                    : t('emp.action.due', { status: tx('actionStatus', a.status), date: fmtDate(a.due_at) })}
                              </div>
                            </li>
                          ))}
                          {f.coaching.map((c, i) => (
                            <li key={`c${i}`}>
                              <strong>{t('timeline.coaching')}</strong> · {who(c.by)}
                              <div className="subtle">
                                {fmtDate(c.at)} · {tx('outcome', c.outcome)}
                              </div>
                            </li>
                          ))}
                        </ul>
                      </td>
                      <td>
                        {f.follow_up ? (
                          <Badge tone={f.follow_up.recurred ? 'warn' : 'ok'}>
                            {t(f.follow_up.recurred ? 'emp.followUp.repeated' : 'emp.followUp.held', {
                              n: f.follow_up.comparable,
                              r: f.follow_up.recurrences,
                            })}
                          </Badge>
                        ) : (
                          <span className="subtle">{t('case.followUpPending')}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <div className="stack">
          <Card title={t('emp.gaps.title')} subtitle={t('emp.gaps.subtitle')}>
            <div data-tour="report-gaps">
              {s.knowledge_gaps.length === 0 ? (
                <Empty>{t('emp.gaps.none')}</Empty>
              ) : (
                <dl className="emp-gaps">
                  {Object.entries(gapsByType).map(([ctype, items]) => (
                    <div key={ctype}>
                      <dt>{tx('caseType', ctype)}</dt>
                      {items.map((g) => (
                        <dd key={g.code}>
                          <Icon name="warn" size={13} /> {t(`gapcode.${g.code}` as MessageKey, { n: g.count })}
                          <span className="subtle"> · {t('emp.gaps.last', { date: fmtDate(g.last_at) })}</span>
                        </dd>
                      ))}
                    </div>
                  ))}
                </dl>
              )}
            </div>
          </Card>

          <Card title={t('emp.outlook.title', { days: data.model.horizon_days })} subtitle={t('emp.outlook.subtitle')}>
            <div className="table-wrap" data-tour="report-outlook">
              <table>
                <thead>
                  <tr>
                    <th>{t('explorer.category')}</th>
                    <th className="num">{t('emp.outlook.chance')}</th>
                    <th>{t('emp.outlook.level')}</th>
                    <th>{t('emp.outlook.why')}</th>
                    <th>{t('emp.outlook.action')}</th>
                  </tr>
                </thead>
                <tbody>
                  {s.outlook.map((o) => (
                    <tr key={o.case_type}>
                      <td>{tx('caseType', o.case_type)}</td>
                      <td className="num">
                        <strong>{fmtPercent(o.probability)}</strong>
                        <div className="subtle">{t('emp.outlook.peers', { p: fmtPercent(o.peer_probability) })}</div>
                      </td>
                      <td>
                        <OutlookBadge item={o} />
                      </td>
                      <td className="subtle">{o.drivers.map((d) => driverText(t, d)).join(' · ')}</td>
                      <td>{t(`reco.${o.recommendation}` as MessageKey)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>

        <Card title={t('emp.model.title')}>
          <dl className="dl">
            <dt>{t('emp.model.name')}</dt>
            <dd>
              {data.model.name} v{data.model.version} · <StatusBadge prefix="model" value={data.model.status} />
            </dd>
            <dt>{t('emp.model.trainedOn')}</dt>
            <dd>
              {t('emp.model.trainedOnValue', {
                cases: fmtNumber(data.model.cases),
                followups: fmtNumber(data.model.follow_ups),
                from: fmtDate(data.model.period_from),
                to: fmtDate(data.model.period_to),
              })}
            </dd>
            <dt>{t('emp.model.method')}</dt>
            <dd>{t('emp.model.methodValue', { k: fmtNumber(data.model.employee_strength, 1) })}</dd>
            <dt>{t('emp.model.effects')}</dt>
            <dd>
              {t('emp.model.effectsValue', {
                done: fmtNumber(data.model.multipliers.actions_completed, 2),
                open: fmtNumber(data.model.multipliers.actions_open, 2),
                und: fmtNumber(data.model.multipliers.understood, 2),
                notund: fmtNumber(data.model.multipliers.not_understood, 2),
              })}
            </dd>
            <dt>{t('case.limitations')}</dt>
            <dd className="subtle">{data.model.limitations}</dd>
          </dl>
          <div className="callout" style={{ marginTop: 10 }}>
            <Icon name="warn" />
            <div>{t('emp.model.disclaimer')}</div>
          </div>
        </Card>
        <p className="print-only subtle">{t('emp.footer', { date: fmtDate(data.generated_at, true) })}</p>
      </div>
    </div>
  );
}
