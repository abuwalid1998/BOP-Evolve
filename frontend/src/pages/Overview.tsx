import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Bar as RBar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { DashboardSummary } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { PageBrief } from '../components/PageBrief';
import { Badge, Bar, Card, ErrorBox, Kpi, LiveStatus, Loading, PageHead, StatusBadge } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useI18n } from '../i18n';

const GENS = ['G0', 'G1', 'G2', 'G3', 'G4', 'G5'];
const AWARENESS = ['recognized', 'not_recognized', 'unsure', 'disagree'];
const WINDOWS = [30, 90, 180];

export default function OverviewPage() {
  const { t, tx, fmtNumber, fmtPercent, fmtDate, fmtRelative, dir } = useI18n();
  const { can } = useAuth();
  const [days, setDays] = useState(90);
  const { data, error, loading, updatedAt, stale, reload } = useApi<DashboardSummary>(
    `/api/dashboard/summary?days=${days}`,
    15000,
  );

  const header = (
    <>
      <PageHead
        title={t('overview.title')}
        subtitle={t('overview.subtitle')}
        actions={
          <>
            <div className="segmented" role="group" aria-label={t('common.window')}>
              {WINDOWS.map((w) => (
                <button key={w} className={w === days ? 'active' : ''} onClick={() => setDays(w)}>
                  {t('overview.window', { n: w })}
                </button>
              ))}
            </div>
            <LiveStatus updatedAt={updatedAt} stale={stale} />
          </>
        }
      />
      <PageBrief page="overview" />
    </>
  );
  if (!data) return <>{header}{loading ? <Loading /> : <ErrorBox error={error} onRetry={reload} />}</>;

  const s = data.totals.by_status;
  const confirmed = (s.CONFIRMED ?? 0) + (s.AMENDED ?? 0);
  const awarenessTotal = AWARENESS.reduce((sum, k) => sum + (data.awareness[k] ?? 0), 0);
  const genTotal = GENS.reduce((sum, k) => sum + (data.generations.distribution[k] ?? 0), 0);
  const trend = data.trend.map((b) => ({ ...b, label: fmtDate(b.week_start) }));
  const p = data.pipelines;

  return (
    <>
      {header}
      <div className="stack">
        <div className="grid grid-4">
          <Kpi label={t('overview.reviewed')} value={fmtNumber(data.totals.reviewed_interactions)} foot={t('overview.window', { n: days })} />
          <Kpi
            label={t('overview.potential')}
            value={fmtNumber(data.totals.potential_findings)}
            foot={`${t('overview.confirmed')} ${fmtNumber(confirmed)} · ${t('overview.disputed')} ${fmtNumber(s.DISPUTED ?? 0)} · ${t('overview.pending')} ${fmtNumber(s.POTENTIAL ?? 0)} · ${t('overview.dismissed')} ${fmtNumber(s.DISMISSED ?? 0)}`}
          />
          <Kpi
            label={t('overview.recurrence')}
            value={fmtPercent(data.recurrence.rate, 1)}
            foot={`${t('common.sample', { n: fmtNumber(data.recurrence.evaluated) })} · ${t('overview.recurrenceHelp')}`}
          />
          <Kpi
            label={t('overview.actionCompletion')}
            value={fmtPercent(data.actions.completion_rate)}
            foot={
              <span className="row" style={{ gap: 6 }}>
                {fmtNumber(data.actions.completed)} / {fmtNumber(data.actions.due_or_completed)}
                {data.actions.overdue > 0 && <Badge tone="warn">{t('overview.overdue', { n: data.actions.overdue })}</Badge>}
              </span>
            }
          />
        </div>

        <div className="grid grid-3">
          <Card title={t('overview.trend')} className="span-2">
            <div style={{ height: 240 }} dir="ltr">
              <ResponsiveContainer>
                <LineChart data={trend} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
                  <CartesianGrid stroke="var(--border)" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'var(--text-3)' }} reversed={dir === 'rtl'} minTickGap={24} />
                  <YAxis tick={{ fontSize: 11, fill: 'var(--text-3)' }} orientation={dir === 'rtl' ? 'right' : 'left'} />
                  <Tooltip
                    contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10 }}
                    formatter={(value: number) => fmtNumber(value, 2)}
                  />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line
                    type="monotone"
                    dataKey="rate_per_100"
                    name={t('insights.rate')}
                    stroke="var(--brand)"
                    strokeWidth={2.5}
                    dot={false}
                    connectNulls
                  />
                  <Line
                    type="monotone"
                    dataKey="pending_per_100"
                    name={t('overview.trendPending')}
                    stroke="var(--text-3)"
                    strokeDasharray="4 4"
                    strokeWidth={1.5}
                    dot={false}
                    connectNulls
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card title={t('overview.awareness')} subtitle={t('case.awarenessNote')}>
            <div className="stack" style={{ gap: 12 }}>
              {AWARENESS.map((k) => {
                const n = data.awareness[k] ?? 0;
                return (
                  <div key={k}>
                    <div className="row between">
                      <span>{tx('awareness', k)}</span>
                      <span className="subtle">
                        {fmtNumber(n)} · {fmtPercent(awarenessTotal ? n / awarenessTotal : null)}
                      </span>
                    </div>
                    <Bar value={awarenessTotal ? n / awarenessTotal : 0} />
                  </div>
                );
              })}
            </div>
          </Card>
        </div>

        <div className="grid grid-3">
          <Card
            title={t('overview.generations')}
            subtitle={t('learning.metaphor')}
            className="span-2"
            actions={
              data.generations.pending_approval > 0 && (
                <Badge tone="warn">{t('overview.pendingApproval', { n: data.generations.pending_approval })}</Badge>
              )
            }
          >
            <div style={{ height: 200 }} dir="ltr">
              <ResponsiveContainer>
                <BarChart
                  data={GENS.map((g) => ({ code: g, label: `${g} · ${tx('gen', g)}`, n: data.generations.distribution[g] ?? 0 }))}
                  margin={{ top: 8, right: 12, bottom: 0, left: -12 }}
                >
                  <CartesianGrid stroke="var(--border)" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'var(--text-3)' }} reversed={dir === 'rtl'} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--text-3)' }} orientation={dir === 'rtl' ? 'right' : 'left'} />
                  <Tooltip
                    contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10 }}
                    formatter={(value: number) => [`${fmtNumber(value)} (${fmtPercent(genTotal ? value / genTotal : null)})`, '']}
                  />
                  <RBar dataKey="n" fill="var(--brand)" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card
            title={t('overview.health')}
            actions={can('ops.view') && <Link to="/health">{t('common.view')}</Link>}
          >
            <dl className="dl">
              <dt>{t('overview.lastIngestion')}</dt>
              <dd>
                {fmtDate(p.last_successful_ingestion_at, true)}
                <div className="subtle">{fmtRelative(p.last_successful_ingestion_at)}</div>
              </dd>
              <dt>{t('overview.worker')}</dt>
              <dd>
                {p.worker.alive ? (
                  <Badge tone="ok">{t('overview.workerAlive')}</Badge>
                ) : (
                  <Badge tone="bad">{t('overview.workerDown')}</Badge>
                )}
              </dd>
              <dt>{t('health.pipelines')}</dt>
              <dd className="row" style={{ gap: 6 }}>
                {Object.entries(p.states).map(([state, n]) => (
                  <span key={state} className="row" style={{ gap: 4 }}>
                    <StatusBadge prefix="pipeline" value={state} />
                    <span className="subtle">×{n}</span>
                  </span>
                ))}
              </dd>
              <dt>{t('health.models')}</dt>
              <dd className="row" style={{ gap: 6 }}>
                {Object.entries(data.models).map(([state, n]) => (
                  <span key={state} className="row" style={{ gap: 4 }}>
                    <StatusBadge prefix="model" value={state} />
                    <span className="subtle">×{n}</span>
                  </span>
                ))}
              </dd>
            </dl>
            {p.alerts.length > 0 && (
              <div className="stack" style={{ gap: 8, marginTop: 14 }}>
                <h3>{t('overview.alerts')}</h3>
                {p.alerts.map((a) => (
                  <div key={a.pipeline} className={`callout ${a.state === 'FAILED' ? 'bad' : ''}`} style={{ padding: '8px 12px' }}>
                    <div>
                      <div className="row" style={{ gap: 6 }}>
                        <strong>{a.name}</strong>
                        <StatusBadge prefix="pipeline" value={a.state} />
                      </div>
                      {a.error && <p>{a.error}</p>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
