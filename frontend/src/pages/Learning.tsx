import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { qs } from '../api/client';
import type { EmployeeListItem } from '../api/types';
import { GenBadge } from '../components/GenerationTrack';
import { PageBrief } from '../components/PageBrief';
import { Badge, Bar, Card, Empty, ErrorBox, Field, Loading, PageHead } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useI18n } from '../i18n';

export default function LearningPage() {
  const { t, pick, fmtPercent } = useI18n();
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const { data, error, loading, reload } = useApi<EmployeeListItem[]>(`/api/employees${qs({ q: query })}`);

  return (
    <>
      <PageHead title={t('learning.title')} subtitle={t('learning.subtitle')} />
      <PageBrief page="learning" />
      <div className="stack">
        <div className="callout brand">
          <div>
            <strong>{t('learning.metaphor')}</strong>
            <p>{t('learning.weightsNote')}</p>
          </div>
        </div>
        <Card
          tour="learning-table"
          title={data ? t('learning.employees', { n: data.length }) : undefined}
          actions={
            <form
              className="row"
              onSubmit={(e) => {
                e.preventDefault();
                setQuery(q);
              }}
            >
              <Field label={t('common.search')}>
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="E-1001" dir="ltr" />
              </Field>
            </form>
          }
        >
          {!data && loading && <Loading />}
          <ErrorBox error={error} onRetry={reload} />
          {data && data.length === 0 && <Empty />}
          {data && data.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{t('explorer.employee')}</th>
                    <th>{t('explorer.unit')}</th>
                    <th>{t('learning.current')}</th>
                    <th>{t('learning.score')}</th>
                    <th className="num">{t('learning.confirmed')}</th>
                    <th className="num">{t('learning.disputed')}</th>
                    <th className="num">{t('learning.pendingReview')}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.map((e) => (
                    <tr key={e.id} className="clickable" tabIndex={0} onClick={() => navigate(`/learning/${e.id}`)}
                      onKeyDown={(ev) => ev.key === 'Enter' && navigate(`/learning/${e.id}`)}>
                      <td>
                        <div className="mono">{e.pseudonym}</div>
                        <div className="subtle">{e.role_title}</div>
                      </td>
                      <td>{pick(e.org_unit.name, e.org_unit.name_ar)}</td>
                      <td>
                        <div className="row" style={{ gap: 6 }}>
                          <GenBadge code={e.current_generation} />
                          {e.pending_generation && <Badge tone="warn">{t('learning.pending')}: {e.pending_generation}</Badge>}
                        </div>
                      </td>
                      <td style={{ minWidth: 140 }}>
                        <Bar value={e.current_score} />
                        <span className="subtle">
                          {fmtPercent(e.current_score)} · {t('learning.coverage')} {fmtPercent(e.current_coverage)}
                        </span>
                      </td>
                      <td className="num">{e.confirmed}</td>
                      <td className="num">{e.disputed}</td>
                      <td className="num">{e.pending_review}</td>
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
