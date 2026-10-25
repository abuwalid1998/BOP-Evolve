import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { qs } from '../api/client';
import type { CaseListItem, Paged, UnitRef } from '../api/types';
import { PageBrief } from '../components/PageBrief';
import { Card, Empty, ErrorBox, Field, LiveStatus, Loading, PageHead, Pager, StatusBadge } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useI18n } from '../i18n';

const STATUSES = ['POTENTIAL', 'DISPUTED', 'CONFIRMED', 'AMENDED', 'DISMISSED'];
const SEVERITIES = ['low', 'medium', 'high', 'critical'];
export const CASE_TYPES = [
  'account_opening',
  'cash_transaction',
  'complaint_handling',
  'card_services',
  'transfers',
  'general_inquiry',
  'loan_inquiry',
];

interface Filters {
  status: string;
  case_type: string;
  severity: string;
  branch: string;
  q: string;
  from: string;
  to: string;
}
const EMPTY: Filters = { status: '', case_type: '', severity: '', branch: '', q: '', from: '', to: '' };

export default function ExplorerPage() {
  const { t, tx, pick, fmtDate, fmtPercent } = useI18n();
  const navigate = useNavigate();
  const [draft, setDraft] = useState<Filters>(EMPTY);
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [page, setPage] = useState(1);
  const units = useApi<(UnitRef & { parent_id: string | null })[]>('/api/admin/org-units');

  const path = `/api/cases${qs({
    ...filters,
    from: filters.from ? new Date(filters.from).toISOString() : '',
    to: filters.to ? new Date(`${filters.to}T23:59:59`).toISOString() : '',
    page,
    page_size: 25,
  })}`;
  const { data, error, loading, updatedAt, stale, reload } = useApi<Paged<CaseListItem>>(path, 20000);

  const set = (key: keyof Filters) => (e: { target: { value: string } }) => setDraft({ ...draft, [key]: e.target.value });
  const apply = () => {
    setPage(1);
    setFilters(draft);
  };

  return (
    <>
      <PageHead title={t('explorer.title')} subtitle={t('explorer.subtitle')} actions={<LiveStatus updatedAt={updatedAt} stale={stale} />} />
      <PageBrief page="explorer" />
      <div className="stack">
        <Card tour="explorer-filters">
          <form
            className="filters"
            onSubmit={(e) => {
              e.preventDefault();
              apply();
            }}
          >
            <Field label={t('common.search')}>
              <input value={draft.q} onChange={set('q')} placeholder={t('explorer.searchPlaceholder')} />
            </Field>
            <Field label={t('explorer.status')}>
              <select value={draft.status} onChange={set('status')}>
                <option value="">{t('common.all')}</option>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {tx('status', s)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t('explorer.category')}>
              <select value={draft.case_type} onChange={set('case_type')}>
                <option value="">{t('common.all')}</option>
                {CASE_TYPES.map((c) => (
                  <option key={c} value={c}>
                    {tx('caseType', c)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t('explorer.severity')}>
              <select value={draft.severity} onChange={set('severity')}>
                <option value="">{t('common.all')}</option>
                {SEVERITIES.map((s) => (
                  <option key={s} value={s}>
                    {tx('severity', s)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t('explorer.unit')}>
              <select value={draft.branch} onChange={set('branch')}>
                <option value="">{t('common.all')}</option>
                {(units.data ?? [])
                  .filter((u) => u.type === 'region' || u.type === 'branch' || u.type === 'department')
                  .map((u) => (
                    <option key={u.id} value={u.id}>
                      {pick(u.name, u.name_ar)}
                    </option>
                  ))}
              </select>
            </Field>
            <Field label={t('explorer.from')}>
              <input type="date" value={draft.from} onChange={set('from')} />
            </Field>
            <Field label={t('explorer.to')}>
              <input type="date" value={draft.to} onChange={set('to')} />
            </Field>
            <div className="row">
              <button className="btn primary" type="submit">
                {t('common.apply')}
              </button>
              <button
                className="btn"
                type="button"
                onClick={() => {
                  setDraft(EMPTY);
                  setFilters(EMPTY);
                  setPage(1);
                }}
              >
                {t('common.reset')}
              </button>
            </div>
          </form>
        </Card>

        <Card tour="explorer-table">
          {!data && loading && <Loading />}
          <ErrorBox error={error} onRetry={reload} />
          {data && data.items.length === 0 && <Empty />}
          {data && data.items.length > 0 && (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>{t('explorer.case')}</th>
                      <th>{t('explorer.occurred')}</th>
                      <th>{t('explorer.category')}</th>
                      <th>{t('explorer.severity')}</th>
                      <th>{t('explorer.status')}</th>
                      <th>{t('explorer.employee')}</th>
                      <th>{t('explorer.unit')}</th>
                      <th>{t('explorer.method')}</th>
                      <th className="num">{t('explorer.confidence')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map((item) => (
                      <tr
                        key={item.finding_id}
                        className="clickable"
                        tabIndex={0}
                        onClick={() => navigate(`/cases/${item.case_id}`)}
                        onKeyDown={(e) => e.key === 'Enter' && navigate(`/cases/${item.case_id}`)}
                      >
                        <td>
                          <div className="id">{item.case_id}</div>
                          <div className="subtle mono">{item.rule_code}</div>
                        </td>
                        <td>{fmtDate(item.occurred_at, true)}</td>
                        <td>{tx('caseType', item.case_type)}</td>
                        <td>
                          <StatusBadge prefix="severity" value={item.severity} />
                        </td>
                        <td>
                          <StatusBadge prefix="status" value={item.status} />
                        </td>
                        <td className="mono">{item.employee.pseudonym}</td>
                        <td>{pick(item.org_unit.name, item.org_unit.name_ar)}</td>
                        <td>{tx('method', item.detection_method)}</td>
                        <td className="num">{fmtPercent(item.confidence)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pager page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />
            </>
          )}
        </Card>
      </div>
    </>
  );
}
