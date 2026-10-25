import { useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { qs } from '../api/client';
import type { UnitRef } from '../api/types';
import { GenBadge } from '../components/GenerationTrack';
import { Icon } from '../components/Icon';
import { PageBrief } from '../components/PageBrief';
import { Badge, Bar, Card, Empty, ErrorBox, Kpi, Loading, PageHead } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useI18n, type MessageKey } from '../i18n';

export type OutlookBand = 'low' | 'moderate' | 'elevated';

export interface OutlookItem {
  case_type: string;
  cases_12m: number;
  confirmed_12m: number;
  expected_cases: number;
  probability: number;
  peer_probability: number;
  relative_risk: number | null;
  expected_repeats: number;
  band: OutlookBand;
  drivers: { code: string; n?: number; ratio?: number }[];
  recommendation: string;
}

export interface KnowledgeGap {
  case_type: string;
  code: string;
  count: number;
  last_at: string;
}

export interface EmployeeSummary {
  cases_12m: number;
  findings_12m: number;
  confirmed_12m: number;
  pending_review: number;
  under_objection: number;
  dismissed: number;
  rate_per_100: number | null;
  repeats: number;
  learning_rate: number | null;
  follow_ups_evaluated: number;
  actions: { total: number; completed: number; on_time: number; open: number; overdue: number; on_time_rate: number | null };
  last_finding_at: string | null;
  stage: string | null;
  stage_since: string | null;
  pending_stage: string | null;
  knowledge_gaps: KnowledgeGap[];
  outlook: OutlookItem[];
  top_outlook: OutlookItem | null;
  propensity: number;
}

export interface ModelInfo {
  name: string;
  version: string;
  status: string;
  limitations: string;
  fitted_at: string;
  period_from: string;
  period_to: string;
  cases: number;
  follow_ups: number;
  employee_strength: number;
  type_strength: number;
  multipliers: Record<string, number>;
  horizon_days: number;
}

interface Aggregate {
  employees: number;
  cases_12m: number;
  confirmed_12m: number;
  rate_per_100: number | null;
  repeats: number;
  learning_rate: number | null;
  avg_stage: number | null;
  open_actions: number;
  overdue_actions: number;
  elevated_outlook: number;
  knowledge_gaps: number;
}

interface EmployeeRow extends EmployeeSummary {
  id: string;
  pseudonym: string;
  role_title: string;
  path: UnitRef[];
}

interface WorkforceView {
  generated_at: string;
  unit: UnitRef | null;
  breadcrumb: UnitRef[];
  totals: Aggregate;
  children: ({ unit: UnitRef } & Aggregate)[];
  employees: EmployeeRow[];
  model: ModelInfo;
}

const BAND_TONE: Record<OutlookBand, 'ok' | 'info' | 'warn'> = { low: 'ok', moderate: 'info', elevated: 'warn' };
const BAND_RANK: Record<OutlookBand, number> = { low: 0, moderate: 1, elevated: 2 };
type Sort = 'outlook' | 'mistakes' | 'recent' | 'stage';

export function OutlookBadge({ item }: { item: OutlookItem | null }) {
  const { tx } = useI18n();
  if (!item) return <span className="subtle">—</span>;
  return (
    <Badge tone={BAND_TONE[item.band]} icon={item.band === 'elevated' ? 'warn' : item.band === 'low' ? 'check' : 'info'}>
      {tx('band', item.band)}
    </Badge>
  );
}

export default function WorkforcePage() {
  const { t, tx, pick, fmtNumber, fmtPercent, fmtDate, fmtRelative } = useI18n();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const unitId = params.get('unit') ?? '';
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<Sort>('outlook');
  const { data, error, loading, reload } = useApi<WorkforceView>(`/api/hr/workforce${qs({ unit_id: unitId })}`);

  const rows = useMemo(() => {
    const list = (data?.employees ?? []).filter(
      (r) => !q || r.pseudonym.toLowerCase().includes(q.toLowerCase()) || r.role_title.toLowerCase().includes(q.toLowerCase()),
    );
    const key: Record<Sort, (r: EmployeeRow) => number> = {
      outlook: (r) => (r.top_outlook ? BAND_RANK[r.top_outlook.band] * 10 + r.top_outlook.probability : -1),
      mistakes: (r) => r.confirmed_12m * 100 + r.repeats,
      recent: (r) => (r.last_finding_at ? new Date(r.last_finding_at).getTime() : 0),
      stage: (r) => -(r.stage ? Number(r.stage.slice(1)) : -1),
    };
    return [...list].sort((a, b) => key[sort](b) - key[sort](a));
  }, [data, q, sort]);

  const pickUnit = (id: string | null) => setParams(id ? { unit: id } : {});
  const totals = data?.totals;

  return (
    <>
      <PageHead title={t('wf.title')} subtitle={t('wf.subtitle')} />
      <PageBrief page="workforce" />
      <ErrorBox error={error} onRetry={reload} />
      {!data && loading && <Loading />}
      {data && totals && (
        <div className="stack">
          <nav className="wf-breadcrumb" aria-label={t('wf.breadcrumb')} data-tour="wf-breadcrumb">
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
          <div className="grid grid-4" data-tour="wf-kpis">
            <Kpi label={t('wf.k.employees')} value={fmtNumber(totals.employees)} foot={t('wf.k.employeesFoot', { n: fmtNumber(totals.cases_12m) })} />
            <Kpi
              label={t('wf.k.rate')}
              value={fmtNumber(totals.rate_per_100, 2)}
              foot={t('wf.k.rateFoot', { c: fmtNumber(totals.confirmed_12m), r: fmtNumber(totals.repeats) })}
            />
            <Kpi label={t('wf.k.learning')} value={fmtPercent(totals.learning_rate)} foot={t('wf.k.learningFoot')} />
            <Kpi
              label={t('wf.k.actions')}
              value={fmtNumber(totals.open_actions)}
              foot={
                <span className="row" style={{ gap: 6 }}>
                  {totals.overdue_actions > 0 && <Badge tone="warn">{t('overview.overdue', { n: totals.overdue_actions })}</Badge>}
                  {t('wf.k.outlookFoot', { n: totals.elevated_outlook })}
                </span>
              }
            />
          </div>

          {data.children.length > 0 && (
            <Card title={t('wf.units.title')} subtitle={t('wf.units.subtitle')}>
              <div className="table-wrap" data-tour="wf-units">
                <table>
                  <thead>
                    <tr>
                      <th>{t('explorer.unit')}</th>
                      <th className="num">{t('wf.k.employees')}</th>
                      <th>{t('wf.k.rate')}</th>
                      <th className="num">{t('wf.col.repeats')}</th>
                      <th className="num">{t('wf.k.learning')}</th>
                      <th className="num">{t('insights.avgGeneration')}</th>
                      <th className="num">{t('wf.col.overdue')}</th>
                      <th className="num">{t('wf.col.elevated')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.children.map((c) => {
                      const max = Math.max(...data.children.map((x) => x.rate_per_100 ?? 0), 1);
                      return (
                        <tr key={c.unit.id} className="clickable" onClick={() => pickUnit(c.unit.id)}>
                          <td>
                            <strong>{pick(c.unit.name, c.unit.name_ar)}</strong>
                            <div className="subtle">{tx('level', c.unit.type)}</div>
                          </td>
                          <td className="num">{fmtNumber(c.employees)}</td>
                          <td style={{ minWidth: 140 }}>
                            {fmtNumber(c.rate_per_100, 2)}
                            <Bar value={(c.rate_per_100 ?? 0) / max} />
                          </td>
                          <td className="num">{fmtNumber(c.repeats)}</td>
                          <td className="num">{fmtPercent(c.learning_rate)}</td>
                          <td className="num">{c.avg_stage !== null ? `G${fmtNumber(c.avg_stage, 1)}` : '—'}</td>
                          <td className="num">{fmtNumber(c.overdue_actions)}</td>
                          <td className="num">{c.elevated_outlook > 0 ? <Badge tone="warn">{c.elevated_outlook}</Badge> : '0'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          <Card
            title={t('wf.emp.title', { n: rows.length })}
            subtitle={t('wf.emp.subtitle')}
            actions={
              <>
                <input
                  aria-label={t('common.search')}
                  placeholder={t('wf.emp.search')}
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  style={{ width: 200 }}
                />
                <div className="segmented" role="group" aria-label={t('wf.sort')}>
                  {(['outlook', 'mistakes', 'recent', 'stage'] as const).map((s) => (
                    <button key={s} className={sort === s ? 'active' : ''} aria-pressed={sort === s} onClick={() => setSort(s)}>
                      {t(`wf.sort.${s}` as MessageKey)}
                    </button>
                  ))}
                </div>
              </>
            }
          >
            {rows.length === 0 ? (
              <Empty />
            ) : (
              <div className="table-wrap" data-tour="wf-table">
                <table>
                  <thead>
                    <tr>
                      <th>{t('explorer.employee')}</th>
                      <th>{t('explorer.unit')}</th>
                      <th>{t('learning.current')}</th>
                      <th className="num">{t('wf.col.mistakes')}</th>
                      <th>{t('wf.col.last')}</th>
                      <th>{t('wf.col.actions')}</th>
                      <th className="num">{t('wf.k.learning')}</th>
                      <th>{t('wf.col.outlook')}</th>
                      <th className="num">{t('wf.col.gaps')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.id} className="clickable" onClick={() => navigate(`/workforce/${r.id}`)}>
                        <td>
                          <Link to={`/workforce/${r.id}`} className="mono" onClick={(e) => e.stopPropagation()}>
                            {r.pseudonym}
                          </Link>
                          <div className="subtle">{r.role_title}</div>
                        </td>
                        <td>{r.path.length ? pick(r.path[r.path.length - 1].name, r.path[r.path.length - 1].name_ar) : '—'}</td>
                        <td>
                          <GenBadge code={r.stage} />
                          {r.pending_stage && <div className="subtle">{t('wf.col.proposed', { code: r.pending_stage })}</div>}
                        </td>
                        <td className="num">
                          <strong>{fmtNumber(r.confirmed_12m)}</strong>
                          {r.repeats > 0 && <div className="subtle">{t('wf.col.repeatsN', { n: r.repeats })}</div>}
                        </td>
                        <td>
                          {r.last_finding_at ? (
                            <>
                              {fmtDate(r.last_finding_at)}
                              <div className="subtle">{fmtRelative(r.last_finding_at)}</div>
                            </>
                          ) : (
                            '—'
                          )}
                        </td>
                        <td>
                          {fmtNumber(r.actions.completed)} / {fmtNumber(r.actions.total)}
                          {r.actions.overdue > 0 && (
                            <div>
                              <Badge tone="warn">{t('overview.overdue', { n: r.actions.overdue })}</Badge>
                            </div>
                          )}
                        </td>
                        <td className="num">{fmtPercent(r.learning_rate)}</td>
                        <td>
                          <OutlookBadge item={r.top_outlook} />
                          {r.top_outlook && <div className="subtle">{tx('caseType', r.top_outlook.case_type)}</div>}
                        </td>
                        <td className="num">{r.knowledge_gaps.length}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="subtle wf-model-note">
              <Icon name="info" size={14} />{' '}
              {t('wf.modelNote', {
                model: `${data.model.name} v${data.model.version}`,
                cases: fmtNumber(data.model.cases),
                followups: fmtNumber(data.model.follow_ups),
              })}
            </p>
          </Card>
        </div>
      )}
    </>
  );
}
