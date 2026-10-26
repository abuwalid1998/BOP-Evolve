import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { AiPanel } from '../components/AiPanel';
import { Icon } from '../components/Icon';
import { PageBrief } from '../components/PageBrief';
import { useTour } from '../components/Tour';
import { Badge, Card, ErrorBox, Loading, PageHead } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useI18n, type Lang, type MessageKey } from '../i18n';

interface Journey {
  steps: { key: 'activated' | 'language' | 'tour' | 'policies' | 'quiz'; done_at: string | null }[];
  completed_at: string | null;
  quiz_score: number | null;
  quiz_attempts: number;
  locale: string;
  wave: { id: string; name: string } | null;
  reminder: { message: string; message_ar: string | null } | null;
  profile: { grade: string | null; job_title: string | null; unit: { name: string; name_ar: string; type: string } | null; roles: string[] };
  policies: { id: string; code: string; version: string; title: string; title_ar: string; summary: string; summary_ar: string; acknowledged: boolean }[];
}

interface Quiz {
  quiz_id: string;
  source: 'ai' | 'built_in';
  model: string | null;
  questions: { question: string; options: string[] }[];
}

interface QuizResult {
  score: number;
  out_of: number;
  passed: boolean;
  review: { correct_index: number; your_index: number; explanation: string | null }[];
  journey: Journey;
}

function QuizCard({ onDone }: { onDone: (j: Journey) => void }) {
  const { t, lang } = useI18n();
  const quiz = useApi<Quiz>(`/api/onboarding/me/quiz?language=${lang}`);
  const [answers, setAnswers] = useState<(number | null)[]>([null, null, null]);
  const [result, setResult] = useState<QuizResult | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  if (!quiz.data) return quiz.loading ? <Loading /> : <ErrorBox error={quiz.error} onRetry={quiz.reload} />;
  const submit = async () => {
    setError(null);
    try {
      const r = await api.post<QuizResult>('/api/onboarding/me/quiz', { quiz_id: quiz.data!.quiz_id, answers });
      setResult(r);
      onDone(r.journey);
    } catch (err) {
      setError(err as ApiError);
    }
  };
  return (
    <div className="stack" style={{ gap: 12 }}>
      <p className="subtle">
        {quiz.data.source === 'ai' ? (
          <>
            <Icon name="spark" size={13} /> {t('welcome.quiz.ai', { model: quiz.data.model ?? '' })}
          </>
        ) : (
          t('welcome.quiz.builtIn')
        )}
      </p>
      {quiz.data.questions.map((q, qi) => (
        <fieldset key={qi} className="quiz-q">
          <legend>
            {qi + 1}. {q.question}
          </legend>
          {q.options.map((o, oi) => {
            const review = result?.review[qi];
            const cls = review ? (oi === review.correct_index ? 'correct' : oi === review.your_index ? 'wrong' : '') : '';
            return (
              <label key={oi} className={`quiz-option ${cls}`}>
                <input
                  type="radio"
                  name={`q${qi}`}
                  checked={answers[qi] === oi}
                  disabled={!!result}
                  onChange={() => setAnswers((prev) => prev.map((a, i) => (i === qi ? oi : a)))}
                />
                {o}
              </label>
            );
          })}
          {result?.review[qi].explanation && <p className="subtle">{result.review[qi].explanation}</p>}
        </fieldset>
      ))}
      {result ? (
        <div className={`callout ${result.passed ? 'brand' : 'info'}`}>
          {result.passed ? t('welcome.quiz.passed', { s: result.score, n: result.out_of }) : t('welcome.quiz.retry', { s: result.score, n: result.out_of })}
          {!result.passed && (
            <button
              className="btn small"
              style={{ marginInlineStart: 12 }}
              onClick={() => {
                setResult(null);
                setAnswers([null, null, null]);
              }}
            >
              {t('welcome.quiz.again')}
            </button>
          )}
        </div>
      ) : (
        <button className="btn primary" disabled={answers.some((a) => a === null)} onClick={submit}>
          {t('welcome.quiz.submit')}
        </button>
      )}
      <ErrorBox error={error} />
    </div>
  );
}

export default function WelcomePage() {
  const { t, tx, pick, lang, setLang, fmtDate } = useI18n();
  const { user } = useAuth();
  const { start } = useTour();
  const { data, error, loading, reload } = useApi<Journey>('/api/onboarding/me');
  const [journey, setJourney] = useState<Journey | null>(null);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  // Keep the quiz on screen after a pass in this visit so the person sees the review.
  const [quizOpen, setQuizOpen] = useState(false);
  const j = journey ?? data;

  useEffect(() => {
    const refresh = () => {
      setJourney(null);
      reload();
    };
    window.addEventListener('bop-evolve:tour-finished', refresh);
    return () => window.removeEventListener('bop-evolve:tour-finished', refresh);
  }, [reload]);

  if (!j) return loading ? <Loading /> : <ErrorBox error={error} onRetry={reload} />;
  const done = (key: string) => j.steps.find((s) => s.key === key)?.done_at;
  const doneCount = j.steps.filter((s) => s.done_at).length;
  const post = async (path: string, body?: unknown) => {
    setBusy(true);
    try {
      setJourney(await api.post<Journey>(path, body));
    } finally {
      setBusy(false);
    }
  };
  const chooseLanguage = async (l: Lang) => {
    setLang(l);
    await post('/api/onboarding/me/language', { locale: l });
  };
  const pending = j.policies.filter((p) => !p.acknowledged);

  return (
    <>
      <PageHead title={t('welcome.title', { name: pick(user?.display_name, user?.display_name_ar) })} subtitle={t('welcome.subtitle')} />
      <PageBrief page="welcome" />
      {j.reminder && (
        <div className="callout info" role="note">
          <Icon name="flag" size={14} /> {lang === 'ar' && j.reminder.message_ar ? j.reminder.message_ar : j.reminder.message}
        </div>
      )}
      <div className="welcome-progress card" data-tour="welcome-steps">
        <div className="row between">
          <strong>{j.completed_at ? t('welcome.done', { date: fmtDate(j.completed_at) }) : t('welcome.progress', { n: doneCount, total: j.steps.length })}</strong>
          {j.wave && <span className="subtle">{t('welcome.wave', { name: j.wave.name })}</span>}
        </div>
        <ol className="welcome-steps">
          {j.steps.map((s, i) => (
            <li key={s.key} className={s.done_at ? 'done' : ''}>
              <span className="welcome-dot">{s.done_at ? <Icon name="check" size={14} /> : i + 1}</span>
              {t(`welcome.step.${s.key}` as MessageKey)}
            </li>
          ))}
        </ol>
      </div>

      <div className="grid grid-2" style={{ alignItems: 'start' }}>
        <div className="stack">
          <AiPanel<{ title: string; message: string; first_week_tips: string[] }>
            feature="onboarding"
            title={t('welcome.ai.title')}
            intro={t('welcome.ai.intro')}
            endpoint="/api/onboarding/me/welcome"
            actionLabel={t('welcome.ai.action')}
            render={(r) => (
              <div className="stack" style={{ gap: 6 }}>
                <strong>{r.output.title}</strong>
                <p>{r.output.message}</p>
                <ul>
                  {r.output.first_week_tips.map((tip) => (
                    <li key={tip}>{tip}</li>
                  ))}
                </ul>
              </div>
            )}
          />
          <Card title={t('welcome.you.title')}>
            <dl className="dl">
              <dt>{t('welcome.you.roles')}</dt>
              <dd>{j.profile.roles.map((r) => tx('role', r)).join(' · ')}</dd>
              {j.profile.job_title && (
                <>
                  <dt>{t('welcome.you.job')}</dt>
                  <dd>{j.profile.job_title}</dd>
                </>
              )}
              {j.profile.unit && (
                <>
                  <dt>{t('explorer.unit')}</dt>
                  <dd>{pick(j.profile.unit.name, j.profile.unit.name_ar)}</dd>
                </>
              )}
            </dl>
          </Card>
        </div>

        <div className="stack">
          <Card title={t('welcome.lang.title')} subtitle={t('welcome.lang.subtitle')} actions={done('language') ? <Badge tone="ok">{t('welcome.complete')}</Badge> : undefined}>
            <div className="segmented" role="group" aria-label={t('lang.label')}>
              <button className={lang === 'ar' && done('language') ? 'active' : ''} disabled={busy} onClick={() => chooseLanguage('ar')} lang="ar">
                العربية
              </button>
              <button className={lang === 'en' && done('language') ? 'active' : ''} disabled={busy} onClick={() => chooseLanguage('en')} lang="en">
                English
              </button>
            </div>
          </Card>

          <Card title={t('welcome.tour.title')} subtitle={t('welcome.tour.subtitle')} actions={done('tour') ? <Badge tone="ok">{t('welcome.complete')}</Badge> : undefined}>
            <button className="btn" onClick={start}>
              <Icon name="compass" size={16} /> {t('welcome.tour.start')}
            </button>
            {!done('tour') && (
              <button className="btn ghost small" style={{ marginInlineStart: 8 }} onClick={() => post('/api/onboarding/me/tour')}>
                {t('welcome.tour.skip')}
              </button>
            )}
          </Card>
        </div>
      </div>

      <Card
        title={t('welcome.policies.title')}
        subtitle={t('welcome.policies.subtitle', { n: j.policies.length })}
        actions={done('policies') ? <Badge tone="ok">{t('welcome.complete')}</Badge> : undefined}
      >
        <ul className="welcome-policies" data-tour="welcome-policies">
          {j.policies.map((p) => (
            <li key={p.id}>
              <label className="row" style={{ alignItems: 'flex-start', gap: 10 }}>
                <input
                  type="checkbox"
                  checked={p.acknowledged || ticked.has(p.id)}
                  disabled={p.acknowledged}
                  onChange={(e) => {
                    const next = new Set(ticked);
                    if (e.target.checked) next.add(p.id);
                    else next.delete(p.id);
                    setTicked(next);
                  }}
                />
                <span>
                  <span className="mono subtle">
                    {p.code} v{p.version}
                  </span>{' '}
                  <strong>{pick(p.title, p.title_ar)}</strong>
                  <br />
                  <span className="subtle">{pick(p.summary, p.summary_ar)}</span>
                </span>
              </label>
            </li>
          ))}
        </ul>
        {pending.length > 0 && (
          <button
            className="btn primary"
            disabled={busy || ticked.size === 0}
            onClick={async () => {
              await post('/api/onboarding/me/acknowledge', { policy_version_ids: [...ticked] });
              setTicked(new Set());
            }}
          >
            {t('welcome.policies.confirm', { n: ticked.size })}
          </button>
        )}
      </Card>

      <Card title={t('welcome.quiz.title')} subtitle={t('welcome.quiz.subtitle')} actions={done('quiz') ? <Badge tone="ok">{t('welcome.complete')}</Badge> : undefined}>
        {done('quiz') && !quizOpen ? (
          <p>{t('welcome.quiz.already', { s: j.quiz_score ?? 0 })}</p>
        ) : done('policies') ? (
          <QuizCard
            onDone={(next) => {
              setQuizOpen(true);
              setJourney(next);
            }}
          />
        ) : (
          <p className="subtle">{t('welcome.quiz.locked')}</p>
        )}
      </Card>

      {j.completed_at && (
        <div className="callout brand">
          <Icon name="check" size={14} /> {t('welcome.next')} <Link to="/">{t('welcome.goHome')}</Link>
        </div>
      )}
    </>
  );
}
