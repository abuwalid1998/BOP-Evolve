import type { ReactNode } from 'react';
import { ApiError } from '../api/client';
import { useI18n, type MessageKey } from '../i18n';
import { Icon, type IconName } from './Icon';

type Tone = 'ok' | 'info' | 'warn' | 'bad' | 'brand' | 'neutral';

const TONE_ICON: Record<Tone, IconName> = {
  ok: 'check',
  info: 'info',
  warn: 'warn',
  bad: 'cross',
  brand: 'dot',
  neutral: 'dot',
};

/** Status tones always pair colour with an icon and text label (never colour alone). */
const STATUS_TONES: Record<string, Tone> = {
  // findings
  POTENTIAL: 'info',
  CONFIRMED: 'brand',
  AMENDED: 'brand',
  DISPUTED: 'warn',
  DISMISSED: 'neutral',
  // pipelines
  HEALTHY: 'ok',
  RUNNING: 'info',
  DEGRADED: 'warn',
  FAILED: 'bad',
  PAUSED: 'neutral',
  STALE: 'warn',
  // models
  DEVELOPMENT: 'neutral',
  VALIDATION: 'info',
  APPROVED: 'ok',
  DEPLOYED: 'ok',
  MONITORING: 'info',
  SUSPENDED: 'bad',
  RETIRED: 'neutral',
  // runs / actions / generations
  succeeded: 'ok',
  partial: 'warn',
  failed: 'bad',
  running: 'info',
  planned: 'neutral',
  in_progress: 'info',
  completed: 'ok',
  cancelled: 'neutral',
  approved: 'ok',
  proposed: 'warn',
  rejected: 'neutral',
  // severity
  low: 'neutral',
  medium: 'info',
  high: 'warn',
  critical: 'bad',
};

export function Badge({ tone = 'neutral', children, icon }: { tone?: Tone; children: ReactNode; icon?: IconName }) {
  return (
    <span className={`badge ${tone === 'neutral' ? '' : tone}`}>
      <Icon name={icon ?? TONE_ICON[tone]} size={12} />
      {children}
    </span>
  );
}

export function StatusBadge({ prefix, value }: { prefix: string; value: string | null | undefined }) {
  const { tx } = useI18n();
  if (!value) return <span className="subtle">—</span>;
  return <Badge tone={STATUS_TONES[value] ?? 'neutral'}>{tx(prefix, value)}</Badge>;
}

export function Card({
  title,
  subtitle,
  actions,
  children,
  className = '',
  tour,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Anchor for the guided tour (data-tour). */
  tour?: string;
}) {
  return (
    <section className={`card ${className}`} data-tour={tour}>
      {(title || actions) && (
        <div className="card-head">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <p className="subtle">{subtitle}</p>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Kpi({ label, value, foot }: { label: ReactNode; value: ReactNode; foot?: ReactNode }) {
  return (
    <div className="card kpi">
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value}</span>
      {foot && <span className="kpi-foot">{foot}</span>}
    </div>
  );
}

export function PageHead({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </header>
  );
}

export function Loading() {
  const { t } = useI18n();
  return (
    <div className="loading" role="status">
      {t('common.loading')}
    </div>
  );
}

export function Empty({ children }: { children?: ReactNode }) {
  const { t } = useI18n();
  return <div className="empty">{children ?? t('common.noData')}</div>;
}

export function ErrorBox({ error, onRetry }: { error: ApiError | Error | null; onRetry?: () => void }) {
  const { t } = useI18n();
  if (!error) return null;
  const status = error instanceof ApiError ? error.status : undefined;
  const message =
    status === 403
      ? t('error.forbidden')
      : status === 404
        ? t('error.notFound')
        : status === 0
          ? t('auth.serverUnreachable')
          : error.message || t('common.error');
  return (
    <div className="error-box" role="alert">
      <span>{message}</span>
      {onRetry && (
        <button className="btn small" onClick={onRetry}>
          {t('common.retry')}
        </button>
      )}
    </div>
  );
}

export function LiveStatus({ updatedAt, stale }: { updatedAt: Date | null; stale: boolean }) {
  const { t, fmtDate } = useI18n();
  return (
    <span className={`live-pill ${stale ? 'stale' : ''}`} aria-live="polite">
      <span className="pulse" />
      {stale
        ? t('common.stale')
        : updatedAt
          ? t('common.lastUpdated', { time: fmtDate(updatedAt.toISOString(), true) })
          : t('common.loading')}
    </span>
  );
}

export function Bar({ value }: { value: number | null | undefined }) {
  const pct = Math.max(0, Math.min(1, value ?? 0)) * 100;
  return (
    <div className="bar" role="presentation">
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Pager({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
}) {
  const { t, fmtNumber } = useI18n();
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="pager">
      <span className="subtle">{t('common.total', { count: fmtNumber(total) })}</span>
      <div className="row">
        <button className="btn small" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          {t('common.prev')}
        </button>
        <span className="subtle">{t('common.page', { page, pages })}</span>
        <button className="btn small" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          {t('common.next')}
        </button>
      </div>
    </div>
  );
}

export function Toast({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="toast" role="status">
      {message}
    </div>
  );
}

export function Field({
  label,
  help,
  children,
}: {
  label: string;
  help?: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      {label}
      {children}
      {help && <span className="help">{help}</span>}
    </label>
  );
}

export function useEnumOptions(prefix: string, values: readonly string[]) {
  const { tx } = useI18n();
  return values.map((v) => ({ value: v, label: tx(prefix, v) }));
}

export type { MessageKey };
