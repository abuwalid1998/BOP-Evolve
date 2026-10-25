import { useState } from 'react';
import { api, ApiError } from '../api/client';
import type { ModelStatus, PipelineOverview, PipelineStatus } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Icon } from '../components/Icon';
import { Badge, Card, ErrorBox, LiveStatus, Loading, PageHead, StatusBadge } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useI18n } from '../i18n';

interface RunsResponse {
  runs: {
    id: string;
    started_at: string;
    status: string;
    records_read: number;
    records_written: number;
    records_rejected: number;
    records_duplicated: number;
    duration_ms: number | null;
    request_id: string;
    error_summary: string | null;
  }[];
  quarantine: { id: string; source_record_key: string | null; reason: string; created_at: string }[];
}

function PipelineRuns({ id }: { id: string }) {
  const { t, fmtDate } = useI18n();
  const { data, error } = useApi<RunsResponse>(`/api/pipelines/${id}/runs?limit=10`, 15000);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  return (
    <div className="grid grid-2" style={{ marginTop: 10 }}>
      <div>
        <h3>{t('health.runs')}</h3>
        <table>
          <tbody>
            {data.runs.map((r) => (
              <tr key={r.id}>
                <td className="subtle">{fmtDate(r.started_at, true)}</td>
                <td>
                  <StatusBadge prefix="run" value={r.status} />
                </td>
                <td className="num mono">
                  {r.records_written}/{r.records_read}
                </td>
                <td className="mono subtle">{r.request_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <h3>{t('health.quarantine')}</h3>
        {data.quarantine.length === 0 ? (
          <span className="subtle">{t('common.none')}</span>
        ) : (
          <table>
            <tbody>
              {data.quarantine.map((q) => (
                <tr key={q.id}>
                  <td className="subtle">{fmtDate(q.created_at, true)}</td>
                  <td className="mono">{q.source_record_key}</td>
                  <td className="mono subtle">{q.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function PipelineCard({ p, onChange }: { p: PipelineStatus; onChange: () => void }) {
  const { t, fmtDate, fmtRelative, fmtNumber } = useI18n();
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const control = async (action: 'pause' | 'resume') => {
    setError(null);
    try {
      await api.post(`/api/pipelines/${p.id}/${action}`);
      onChange();
    } catch (err) {
      setError(err as ApiError);
    }
  };

  return (
    <Card
      title={
        <span className="row" style={{ gap: 8 }}>
          {p.name}
          <StatusBadge prefix="pipeline" value={p.state} />
          {p.sla_breached && <Badge tone="bad">{t('health.slaBreached')}</Badge>}
          {!p.source.approved && <Badge tone="warn">{t('health.notApproved')}</Badge>}
        </span>
      }
      subtitle={`${p.source.name} · ${t('health.sla', { n: p.freshness_sla_minutes })}`}
      actions={
        <>
          {can('ops.manage') &&
            (p.state === 'PAUSED' ? (
              <button className="btn small" onClick={() => control('resume')} disabled={!p.source.approved}>
                <Icon name="play" size={14} />
                {t('health.resume')}
              </button>
            ) : (
              <button className="btn small" onClick={() => control('pause')}>
                <Icon name="pause" size={14} />
                {t('health.pause')}
              </button>
            ))}
          <button className="btn small ghost" onClick={() => setOpen(!open)} aria-expanded={open}>
            {t('health.runs')}
          </button>
        </>
      }
    >
      <dl className="dl">
        <dt>{t('health.lastSuccess')}</dt>
        <dd>
          {fmtDate(p.last_success_at, true)} <span className="subtle">({fmtRelative(p.last_success_at)})</span>
        </dd>
        <dt>{t('health.nextRun')}</dt>
        <dd>{p.state === 'PAUSED' ? '—' : fmtRelative(p.next_run_at)}</dd>
        <dt>{t('health.freshness')}</dt>
        <dd>
          {p.freshness_minutes === null ? '—' : `${fmtNumber(p.freshness_minutes, 0)} min`}
          {' · '}
          {t('health.queueLag')} {fmtNumber(p.queue_lag_seconds)} s
        </dd>
        {p.last_run && (
          <>
            <dt>{t('health.records')}</dt>
            <dd>
              {fmtNumber(p.last_run.records_read)} {t('health.read')} · {fmtNumber(p.last_run.records_written)} {t('health.written')} ·{' '}
              {fmtNumber(p.last_run.records_rejected)} {t('health.rejected')} · {fmtNumber(p.last_run.records_duplicated)}{' '}
              {t('health.duplicated')}
            </dd>
          </>
        )}
        {p.last_error && (
          <>
            <dt>{t('health.lastError')}</dt>
            <dd style={{ color: 'var(--bad)' }}>{p.last_error}</dd>
          </>
        )}
        <dt>{t('health.requestId')}</dt>
        <dd className="mono">{p.last_request_id ?? '—'}</dd>
        <dt>{t('health.owner')}</dt>
        <dd>
          {p.owner} ·{' '}
          <a href={p.runbook_url} target="_blank" rel="noreferrer noopener">
            {t('health.runbook')}
          </a>
        </dd>
      </dl>
      <ErrorBox error={error} />
      {open && <PipelineRuns id={p.id} />}
    </Card>
  );
}

export default function HealthPage() {
  const { t, fmtDate, fmtPercent, fmtNumber } = useI18n();
  const pipelines = useApi<{ generated_at: string; overview: PipelineOverview; pipelines: PipelineStatus[] }>(
    '/api/pipelines/status',
    10000,
  );
  const models = useApi<{ generated_at: string; models: ModelStatus[] }>('/api/models/status', 20000);

  return (
    <>
      <PageHead
        title={t('health.title')}
        subtitle={t('health.subtitle')}
        actions={<LiveStatus updatedAt={pipelines.updatedAt} stale={pipelines.stale} />}
      />
      <div className="stack">
        {pipelines.data && !pipelines.data.overview.worker.alive && (
          <div className="callout bad">
            <strong>
              {t('overview.worker')}: {t('overview.workerDown')}
            </strong>
          </div>
        )}
        <h2>{t('health.pipelines')}</h2>
        {!pipelines.data && pipelines.loading && <Loading />}
        <ErrorBox error={pipelines.error} onRetry={pipelines.reload} />
        <div className="grid grid-2">
          {pipelines.data?.pipelines.map((p) => (
            <PipelineCard key={p.id} p={p} onChange={pipelines.reload} />
          ))}
        </div>

        <h2>{t('health.models')}</h2>
        <div className="callout info">{t('health.simulatedStatus')}</div>
        <Card>
          {!models.data && models.loading && <Loading />}
          <ErrorBox error={models.error} onRetry={models.reload} />
          {models.data && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{t('health.models')}</th>
                    <th>{t('explorer.status')}</th>
                    <th>{t('health.lastValidation')}</th>
                    <th>{t('health.lastRun')}</th>
                    <th className="num">{t('health.latency')}</th>
                    <th className="num">{t('health.missing')}</th>
                    <th className="num">{t('health.drift')}</th>
                    <th className="num">{t('health.override')}</th>
                    <th className="num">{t('health.runs30')}</th>
                    <th>{t('case.limitations')}</th>
                  </tr>
                </thead>
                <tbody>
                  {models.data.models.map((m) => (
                    <tr key={m.id}>
                      <td>
                        <strong>{m.name}</strong> <span className="mono subtle">v{m.version}</span>
                        <div className="subtle">{m.purpose}</div>
                      </td>
                      <td>
                        <StatusBadge prefix="model" value={m.status} />
                      </td>
                      <td>{fmtDate(m.last_validation_at)}</td>
                      <td>{fmtDate(m.last_run_at, true)}</td>
                      <td className="num">{m.latency_ms_p50 === null ? '—' : `${fmtNumber(m.latency_ms_p50)} ms`}</td>
                      <td className="num">{fmtPercent(m.missing_input_rate, 1)}</td>
                      <td className="num">
                        {m.drift_score === null ? '—' : fmtNumber(m.drift_score, 2)}
                        {m.drift_score !== null && m.drift_score > 0.2 && (
                          <>
                            {' '}
                            <Badge tone="warn">!</Badge>
                          </>
                        )}
                      </td>
                      <td className="num">{fmtPercent(m.override_rate, 1)}</td>
                      <td className="num">{fmtNumber(m.runs_30d)}</td>
                      <td className="subtle" style={{ maxWidth: 260 }}>
                        {m.limitations}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
