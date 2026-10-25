import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useLocation, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { useI18n, type MessageKey } from '../i18n';
import { Icon } from './Icon';

/**
 * Guided system tour.
 *
 * Each step names a page (resolved at start, e.g. "a confirmed case" or "the employee
 * with the most findings") and an element marked with data-tour="...". The overlay dims
 * the screen, a spotlight glides to the element, and a card fades in beside it with
 * Previous / Next / Finish. Steps the person's role cannot open are skipped.
 * Arrow keys move between steps (mirrored in Arabic); Escape finishes.
 */

interface Targets {
  caseId: string | null;
  employeeId: string | null;
}

interface StepDef {
  id: string;
  /** Any of these permissions shows the step; none means everyone. */
  permissions?: string[];
  route?: string | ((t: Targets) => string | null);
  target?: string;
}

const STEPS: StepDef[] = [
  { id: 'welcome' },
  { id: 'overview', permissions: ['dashboard.view'], route: '/overview', target: 'overview-kpis' },
  { id: 'trend', permissions: ['dashboard.view'], route: '/overview', target: 'overview-trend' },
  { id: 'loop', permissions: ['dashboard.view', 'rules.view'], route: '/data-flow', target: 'how-map' },
  { id: 'register', permissions: ['cases.view'], route: '/explorer', target: 'explorer-table' },
  { id: 'caseWhy', permissions: ['cases.view'], route: (t) => (t.caseId ? `/cases/${t.caseId}` : null), target: 'case-why' },
  { id: 'caseVoice', permissions: ['cases.view'], route: (t) => (t.caseId ? `/cases/${t.caseId}` : null), target: 'case-voice' },
  { id: 'caseReview', permissions: ['cases.view'], route: (t) => (t.caseId ? `/cases/${t.caseId}` : null), target: 'case-review' },
  { id: 'caseActions', permissions: ['cases.view'], route: (t) => (t.caseId ? `/cases/${t.caseId}` : null), target: 'case-actions' },
  { id: 'development', permissions: ['learning.view'], route: '/learning', target: 'learning-table' },
  { id: 'stages', permissions: ['learning.view'], route: (t) => (t.employeeId ? `/learning/${t.employeeId}` : null), target: 'profile-track' },
  { id: 'workforce', permissions: ['workforce.view'], route: '/workforce', target: 'wf-units' },
  { id: 'workforceTable', permissions: ['workforce.view'], route: '/workforce', target: 'wf-table' },
  { id: 'report', permissions: ['workforce.view'], route: (t) => (t.employeeId ? `/workforce/${t.employeeId}` : null), target: 'report-kpis' },
  { id: 'reportTimeline', permissions: ['workforce.view'], route: (t) => (t.employeeId ? `/workforce/${t.employeeId}` : null), target: 'report-timeline' },
  { id: 'reportTypes', permissions: ['workforce.view'], route: (t) => (t.employeeId ? `/workforce/${t.employeeId}` : null), target: 'report-types' },
  { id: 'reportGaps', permissions: ['workforce.view'], route: (t) => (t.employeeId ? `/workforce/${t.employeeId}` : null), target: 'report-gaps' },
  { id: 'reportOutlook', permissions: ['workforce.view'], route: (t) => (t.employeeId ? `/workforce/${t.employeeId}` : null), target: 'report-outlook' },
  { id: 'reportPrint', permissions: ['workforce.view'], route: (t) => (t.employeeId ? `/workforce/${t.employeeId}` : null), target: 'report-print' },
  { id: 'insights', permissions: ['insights.view'], route: '/insights', target: 'insights-table' },
  { id: 'planning', permissions: ['simulations.run'], route: '/scenarios', target: 'scenarios-form' },
  { id: 'rules', permissions: ['rules.view'], route: '/rules', target: 'rules-detail' },
  { id: 'reports', permissions: ['reports.view', 'reports.ops'], route: '/reports', target: 'reports-list' },
  { id: 'finish', target: 'tour-button' },
];

const DONE_KEY = 'bop-evolve.tour.done.';
const FADE_MS = 220;
const PAD = 8;

interface TourValue {
  active: boolean;
  start: () => void;
}

const TourContext = createContext<TourValue>({ active: false, start: () => undefined });

export function useTour() {
  return useContext(TourContext);
}

export function tourSeen(username: string): boolean {
  try {
    return localStorage.getItem(DONE_KEY + username) === '1';
  } catch {
    return true;
  }
}

async function resolveTargets(can: (...p: string[]) => boolean): Promise<Targets> {
  const targets: Targets = { caseId: null, employeeId: null };
  const jobs: Promise<void>[] = [];
  if (can('cases.view')) {
    jobs.push(
      api
        .get<{ items: { case_id: string; occurred_at: string }[] }>('/api/cases?status=CONFIRMED&page_size=50')
        .then((r) => {
          // A case old enough to have its review, actions and follow-up completed.
          const cutoff = Date.now() - 45 * 86400_000;
          const item = r.items.find((i) => new Date(i.occurred_at).getTime() < cutoff) ?? r.items[0];
          targets.caseId = item?.case_id ?? null;
        })
        .catch(() => undefined),
    );
  }
  if (can('workforce.view')) {
    jobs.push(
      api
        .get<{ employees: { id: string; confirmed_12m: number; stage: string | null }[] }>('/api/hr/workforce')
        .then((r) => {
          const ranked = [...r.employees].sort((a, b) => b.confirmed_12m - a.confirmed_12m);
          targets.employeeId = (ranked.find((e) => e.stage) ?? ranked[0])?.id ?? null;
        })
        .catch(() => undefined),
    );
  } else if (can('learning.view')) {
    jobs.push(
      api
        .get<{ id: string; confirmed: number }[]>('/api/employees')
        .then((r) => {
          targets.employeeId = [...r].sort((a, b) => b.confirmed - a.confirmed)[0]?.id ?? null;
        })
        .catch(() => undefined),
    );
  }
  await Promise.all(jobs);
  return targets;
}

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

function rectOf(el: Element): Rect {
  const r = el.getBoundingClientRect();
  return { top: r.top - PAD, left: r.left - PAD, width: r.width + PAD * 2, height: r.height + PAD * 2 };
}

function TourOverlay({
  steps,
  targets,
  onFinish,
}: {
  steps: StepDef[];
  targets: Targets;
  onFinish: () => void;
}) {
  const { t, dir } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const [index, setIndex] = useState(0);
  // The step whose card is shown; the card hides in the same render the step changes.
  const [shown, setShown] = useState<number | null>(null);
  const [rect, setRect] = useState<Rect | null>(null);
  const [cardPos, setCardPos] = useState<{ top: number; left: number } | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const targetEl = useRef<Element | null>(null);
  const step = steps[index];
  const visible = shown === index;
  const reduced = useMemo(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches, []);

  // Move to the step: fade out, navigate, wait for the element, scroll it into view, fade in.
  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      await new Promise((r) => setTimeout(r, reduced ? 0 : FADE_MS));
      const route = typeof step.route === 'function' ? step.route(targets) : step.route;
      const here = location.pathname;
      if (route && route !== here) navigate(route);
      let el: Element | null = null;
      if (step.target) {
        for (let i = 0; i < 80 && !cancelled; i++) {
          el = document.querySelector(`[data-tour="${step.target}"]`);
          if (el && el.getBoundingClientRect().height > 0) break;
          el = null;
          await new Promise((r) => setTimeout(r, 100));
        }
      }
      if (cancelled) return;
      targetEl.current = el;
      if (el) {
        // Scroll to a computed position and wait until the page gets there (smooth scrolling can
        // start late, so "it stopped moving" alone is not enough). Tall elements show their top.
        const r = el.getBoundingClientRect();
        const maxY = document.documentElement.scrollHeight - window.innerHeight;
        const wanted =
          r.height > window.innerHeight - 200
            ? window.scrollY + r.top - 110
            : window.scrollY + r.top + r.height / 2 - window.innerHeight / 2;
        const targetY = Math.round(Math.min(maxY, Math.max(0, wanted)));
        window.scrollTo({ top: targetY, behavior: reduced ? 'auto' : 'smooth' });
        for (let i = 0; i < 50 && !cancelled && Math.abs(window.scrollY - targetY) > 2; i++) {
          await new Promise((res) => setTimeout(res, 50));
        }
        await new Promise((res) => setTimeout(res, 60));
        if (cancelled) return;
        setRect(rectOf(el));
      } else {
        setRect(null);
      }
      setShown(index);
    };
    run();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index]);

  // Keep the spotlight on the element while the page scrolls, resizes or reflows.
  useEffect(() => {
    const update = () => {
      if (targetEl.current && document.contains(targetEl.current)) setRect(rectOf(targetEl.current));
    };
    window.addEventListener('resize', update);
    window.addEventListener('scroll', update, true);
    const ro = new ResizeObserver(update);
    if (targetEl.current) ro.observe(targetEl.current);
    return () => {
      window.removeEventListener('resize', update);
      window.removeEventListener('scroll', update, true);
      ro.disconnect();
    };
  }, [visible]);

  // Place the card next to the spotlight, inside the viewport.
  useLayoutEffect(() => {
    const card = cardRef.current;
    if (!card) return;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const cw = card.offsetWidth;
    const ch = card.offsetHeight;
    if (!rect) {
      setCardPos({ top: Math.max(16, (vh - ch) / 2), left: Math.max(16, (vw - cw) / 2) });
      return;
    }
    const gap = 14;
    const clampLeft = (x: number) => Math.min(vw - cw - 12, Math.max(12, x));
    const clampTop = (y: number) => Math.min(vh - ch - 12, Math.max(12, y));
    const below = rect.top + rect.height + gap;
    const above = rect.top - gap - ch;
    let top: number;
    let left = clampLeft(dir === 'rtl' ? rect.left + rect.width - cw : rect.left);
    if (below + ch < vh - 12) top = below;
    else if (above > 12) top = above;
    else {
      // Too tall to fit the card above or below: beside it, or over its lower corner.
      const side = dir === 'rtl' ? rect.left - gap - cw : rect.left + rect.width + gap;
      if (side > 12 && side + cw < vw - 12) {
        left = side;
        top = clampTop(rect.top + 12);
      } else {
        left = clampLeft(dir === 'rtl' ? 24 : vw - cw - 24);
        top = vh - ch - 24;
      }
    }
    setCardPos({ top, left });
  }, [rect, visible, index, dir]);

  useEffect(() => {
    if (visible) nextRef.current?.focus({ preventScroll: true });
  }, [visible]);

  const last = index === steps.length - 1;
  const go = useCallback(
    (delta: number) => setIndex((i) => Math.min(steps.length - 1, Math.max(0, i + delta))),
    [steps.length],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onFinish();
      const forward = dir === 'rtl' ? 'ArrowLeft' : 'ArrowRight';
      const back = dir === 'rtl' ? 'ArrowRight' : 'ArrowLeft';
      if (e.key === forward) (last ? onFinish() : go(1));
      if (e.key === back) go(-1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [go, last, onFinish, dir]);

  const k = (part: string) => `tour.${step.id}.${part}` as MessageKey;
  return createPortal(
    <div className={`tour${reduced ? ' reduced' : ''}`} role="presentation">
      <div className="tour-blocker" />
      <div className={`tour-dim${rect ? '' : ' on'}`} />
      <div
        className={`tour-spot${rect ? ' on' : ''}`}
        style={rect ? { top: rect.top, left: rect.left, width: rect.width, height: rect.height } : undefined}
        aria-hidden="true"
      />
      <div
        ref={cardRef}
        className={`tour-card${visible ? ' in' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        aria-describedby="tour-body"
        style={cardPos ? { top: cardPos.top, left: cardPos.left } : { visibility: 'hidden' }}
      >
        <div className="tour-progress" aria-hidden="true">
          <span style={{ width: `${((index + 1) / steps.length) * 100}%` }} />
        </div>
        <div className="row between" style={{ gap: 8 }}>
          <span className="subtle tour-count">{t('tour.step', { n: index + 1, total: steps.length })}</span>
          <button className="btn small ghost" onClick={onFinish}>
            {t('tour.finish')}
          </button>
        </div>
        <h2 id="tour-title">{t(k('title'))}</h2>
        <p id="tour-body">{t(k('body'))}</p>
        <div className="row tour-nav">
          <button className="btn" onClick={() => go(-1)} disabled={index === 0}>
            <span className="tour-arrow back" aria-hidden="true">
              <Icon name="play" size={12} />
            </span>
            {t('tour.previous')}
          </button>
          <button ref={nextRef} className="btn primary" onClick={() => (last ? onFinish() : go(1))}>
            {last ? t('tour.done') : t('tour.next')}
            {!last && (
              <span className="tour-arrow" aria-hidden="true">
                <Icon name="play" size={12} />
              </span>
            )}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

export function TourProvider({ children }: { children: ReactNode }) {
  const { user, can } = useAuth();
  const [session, setSession] = useState<{ steps: StepDef[]; targets: Targets } | null>(null);
  const [loading, setLoading] = useState(false);

  const start = useCallback(async () => {
    if (loading) return;
    setLoading(true);
    const targets = await resolveTargets(can);
    const steps = STEPS.filter((s) => {
      if (s.permissions && !can(...s.permissions)) return false;
      if (typeof s.route === 'function' && !s.route(targets)) return false;
      return true;
    });
    setLoading(false);
    setSession({ steps, targets });
  }, [can, loading]);

  const finish = useCallback(() => {
    setSession(null);
    if (user) {
      try {
        localStorage.setItem(DONE_KEY + user.username, '1');
      } catch {
        /* storage unavailable */
      }
    }
  }, [user]);

  const value = useMemo(() => ({ active: !!session || loading, start }), [session, loading, start]);
  return (
    <TourContext.Provider value={value}>
      {children}
      {session && <TourOverlay steps={session.steps} targets={session.targets} onFinish={finish} />}
    </TourContext.Provider>
  );
}
