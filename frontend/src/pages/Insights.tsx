import { useState } from 'react';
import type { InsightGroup } from '../api/types';
import { Bar, Card, Empty, ErrorBox, Loading, PageHead } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useI18n } from '../i18n';

const LEVELS = ['department', 'region', 'branch', 'section'];

interface InsightsResponse {
  level: string;
  window_days: number;
  privacy: { min_employees: number; min_cases: number };
  groups: InsightGroup[];
}

export default function InsightsPage() {
  const { t, tx, pick, fmtNumber, fmtPercent } = useI18n();
  const [level, setLevel] = useState('branch');
  const [days, setDays] = useState(90);
  const { data, error, loading, reload } = useApi<InsightsResponse>(`/api/insights/teams?level=${level}&days=${days}`, 30000);

  return (
    <>
      <PageHead
        title={t('insights.title')}
        subtitle={t('insights.subtitle')}
        actions={
          <>
            <div className="segmented" role="group" aria-label={t('insights.level')}>
              {LEVELS.map((l) => (
                <button key={l} className={l === level ? 'active' : ''} onClick={() => setLevel(l)}>
                  {tx('level', l)}
                </button>
              ))}
            </div>
            <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label={t('common.window')}>
              {[30, 90, 180, 365].map((d) => (
                <option key={d} value={d}>
                  {t('overview.window', { n: d })}
                </option>
              ))}
            </select>
          </>
        }
      />
      <div className="stack">
        {data && (
          <div className="callout info">
            <div>
              <strong>{t('insights.privacy', { emp: data.privacy.min_employees, cases: data.privacy.min_cases })}</strong>
              <p>{t('insights.caseMixNote')}</p>
            </div>
          </div>
        )}
        <Card>
          {!data && loading && <Loading />}
          <ErrorBox error={error} onRetry={reload} />
          {data && data.groups.length === 0 && <Empty />}
          {data && data.groups.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{tx('level', level)}</th>
                    <th className="num">{t('insights.employees')}</th>
                    <th className="num">{t('learning.cases')}</th>
                    <th className="num">{t('overview.confirmed')}</th>
                    <th className="num">{t('overview.disputed')}</th>
                    <th className="num">{t('insights.rate')}</th>
                    <th>{t('overview.recurrence')}</th>
                    <th>{t('overview.actionCompletion')}</th>
                    <th title={t('insights.systemicHelp')}>{t('insights.systemic')}</th>
                    <th className="num">{t('insights.avgGeneration')}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.groups.map((g) =>
                    g.suppressed ? (
                      <tr key={g.org_unit.id}>
                        <td>{pick(g.org_unit.name, g.org_unit.name_ar)}</td>
                        <td colSpan={9} className="subtle">
                          {t('insights.suppressed')}
                        </td>
                      </tr>
                    ) : (
                      <tr key={g.org_unit.id}>
                        <td>{pick(g.org_unit.name, g.org_unit.name_ar)}</td>
                        <td className="num">{fmtNumber(g.employees)}</td>
                        <td className="num">{fmtNumber(g.cases)}</td>
                        <td className="num">{fmtNumber(g.confirmed)}</td>
                        <td className="num">{fmtNumber(g.disputed)}</td>
                        <td className="num">{fmtNumber(g.rate_per_100, 2)}</td>
                        <td style={{ minWidth: 110 }}>
                          <Bar value={g.recurrence_rate} />
                          <span className="subtle">{fmtPercent(g.recurrence_rate)}</span>
                        </td>
                        <td style={{ minWidth: 110 }}>
                          <Bar value={g.action_completion} />
                          <span className="subtle">{fmtPercent(g.action_completion)}</span>
                        </td>
                        <td style={{ minWidth: 110 }}>
                          <Bar value={g.systemic_share} />
                          <span className="subtle">{fmtPercent(g.systemic_share)}</span>
                        </td>
                        <td className="num">{g.avg_generation === null ? '—' : `G${fmtNumber(g.avg_generation, 1)}`}</td>
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
