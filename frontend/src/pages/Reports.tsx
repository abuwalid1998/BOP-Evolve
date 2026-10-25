import { useEffect, useState } from 'react';
import { downloadCsv } from '../api/client';
import type { ReportResult } from '../api/types';
import { Icon } from '../components/Icon';
import { Card, Empty, ErrorBox, Loading, PageHead } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useI18n, type MessageKey } from '../i18n';

export default function ReportsPage() {
  const { t, fmtNumber } = useI18n();
  const catalogue = useApi<{ code: string; title: string }[]>('/api/reports');
  const [code, setCode] = useState<string | null>(null);
  const [days, setDays] = useState(180);

  useEffect(() => {
    if (!code && catalogue.data?.length) setCode(catalogue.data[0].code);
  }, [catalogue.data, code]);

  const report = useApi<ReportResult>(code ? `/api/reports/${code}?days=${days}` : null);

  return (
    <>
      <PageHead
        title={t('reports.title')}
        subtitle={t('reports.subtitle')}
        actions={
          <>
            <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label={t('common.window')}>
              {[30, 90, 180, 365].map((d) => (
                <option key={d} value={d}>
                  {t('overview.window', { n: d })}
                </option>
              ))}
            </select>
            <button
              className="btn"
              disabled={!code}
              onClick={() => code && downloadCsv(`/api/reports/${code}?days=${days}&format=csv`, `bop-evolve-${code}.csv`)}
            >
              <Icon name="download" size={16} />
              {t('common.exportCsv')}
            </button>
          </>
        }
      />
      <div className="tabs" role="tablist">
        {(catalogue.data ?? []).map((r) => (
          <button key={r.code} role="tab" aria-selected={r.code === code} className={r.code === code ? 'active' : ''} onClick={() => setCode(r.code)}>
            {t(`report.${r.code}` as MessageKey)}
          </button>
        ))}
      </div>
      <Card>
        {(catalogue.loading || report.loading) && !report.data && <Loading />}
        <ErrorBox error={catalogue.error || report.error} onRetry={report.reload} />
        {report.data && report.data.rows.length === 0 && <Empty />}
        {report.data && report.data.rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  {report.data.columns.map((c) => (
                    <th key={c} className="mono">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {report.data.rows.map((row, i) => (
                  <tr key={i}>
                    {row.map((cell, j) => (
                      <td key={j} className={typeof cell === 'number' ? 'num' : ''}>
                        {typeof cell === 'number' ? fmtNumber(cell, 3) : cell ?? '—'}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
