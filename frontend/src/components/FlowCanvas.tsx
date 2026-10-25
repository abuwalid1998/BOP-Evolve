import { useEffect, useRef } from 'react';
import { useI18n } from '../i18n';

/**
 * Ambient "data becoming answers" animation.
 *
 * Five stages (raw data → trusted data → information → knowledge → answers) are
 * drawn as bands. Particles start as scattered, jittery fragments, snap into
 * lanes after validation, merge as lanes converge, and arrive as bright nodes
 * that ripple when an answer is delivered. Flow follows the reading direction
 * (mirrored in RTL). Colours come from the `--flow-raw` / `--flow-fine` CSS
 * variables (as "r,g,b" triples) so the same canvas suits dark and light panels.
 *
 * Respects `prefers-reduced-motion` (renders one static frame) and pauses when
 * the tab is hidden or the canvas is off-screen.
 */

const STAGES = 5;
// Lanes per stage: many raw streams are validated, merged and finally condensed into a few answers.
const LANES = [8, 8, 5, 3, 2];
const SIZE = [2.8, 3, 3.5, 4.2, 5.2];
const ALPHA = [0.45, 0.58, 0.72, 0.88, 1];
const JITTER = [16, 6, 2.4, 1, 0];

interface Particle {
  p: number; // progress 0..1 along the flow
  speed: number; // progress per second
  lane: number; // 0..7 source lane (collapses as lanes merge)
  rawY: number; // 0..1 raw scatter position
  seed: number;
}

interface Ripple {
  x: number;
  y: number;
  t: number;
}

const clamp = (v: number, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const smooth = (t: number) => t * t * (3 - 2 * t);
const keyframe = (table: number[], stageF: number) => {
  const i = Math.min(table.length - 2, Math.floor(stageF));
  return lerp(table[i], table[i + 1], clamp(stageF - i));
};

function readTriple(el: Element, name: string, fallback: string): string {
  const raw = getComputedStyle(el).getPropertyValue(name).trim();
  return /^\d+\s*,\s*\d+\s*,\s*\d+$/.test(raw) ? raw : fallback;
}

export interface FlowCanvasProps {
  /** Number of particles per 10,000 px² of canvas area. */
  density?: number;
  /** Draw faint gate lines between stages. */
  gates?: boolean;
  className?: string;
}

export function FlowCanvas({ density = 1, gates = true, className = '' }: FlowCanvasProps) {
  const ref = useRef<HTMLCanvasElement>(null);
  const { dir } = useI18n();

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;

    const rtl = dir === 'rtl';
    const reduceQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    let reduced = reduceQuery.matches;
    let width = 0;
    let height = 0;
    let raf = 0;
    let last = 0;
    let visible = true;
    let colors = { raw: '255,255,255', fine: '255,214,232' };
    let particles: Particle[] = [];
    const ripples: Ripple[] = [];

    const spawn = (initial: boolean): Particle => ({
      p: initial ? Math.random() : -Math.random() * 0.05,
      speed: 1 / (9 + Math.random() * 7),
      lane: Math.floor(Math.random() * LANES[0]),
      rawY: 0.06 + Math.random() * 0.88,
      seed: Math.random() * 1000,
    });

    const laneY = (stage: number, p: Particle) => {
      if (stage === 0) return p.rawY * height;
      const count = LANES[stage];
      const idx = Math.min(count - 1, Math.floor((p.lane * count) / LANES[0]));
      return height * (0.14 + (0.72 * (idx + 0.5)) / count);
    };

    // Vertical position at progress `pr`: hold within a stage, glide to the next lane in its last 45 %.
    const yAt = (p: Particle, pr: number, time: number) => {
      const f = clamp(pr, 0, 0.9999) * STAGES;
      const s = Math.floor(f);
      const u = f - s;
      const from = laneY(s, p);
      const to = s < STAGES - 1 ? laneY(s + 1, p) : from;
      const base = lerp(from, to, smooth(clamp((u - 0.55) / 0.45)));
      const amp = keyframe(JITTER, f) * (height / 420);
      return base + Math.sin(time * 1.6 + p.seed) * amp + Math.sin(time * 0.7 + p.seed * 2.3) * amp * 0.5;
    };

    const xAt = (pr: number) => (rtl ? width * (1 - pr) : width * pr);

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = Math.max(1, Math.round(rect.width));
      height = Math.max(1, Math.round(rect.height));
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const target = Math.round(clamp(((width * height) / 10000) * density, 28, 170));
      while (particles.length < target) particles.push(spawn(true));
      particles.length = Math.min(particles.length, target);
      colors = {
        raw: readTriple(canvas, '--flow-raw', colors.raw),
        fine: readTriple(canvas, '--flow-fine', colors.fine),
      };
      if (reduced) draw(0);
    };

    const draw = (time: number) => {
      ctx.clearRect(0, 0, width, height);

      if (gates) {
        ctx.save();
        ctx.setLineDash([2, 7]);
        ctx.lineWidth = 1;
        ctx.strokeStyle = `rgba(${colors.fine},0.16)`;
        for (let i = 1; i < STAGES; i++) {
          const x = Math.round(xAt(i / STAGES)) + 0.5;
          ctx.beginPath();
          ctx.moveTo(x, 0);
          ctx.lineTo(x, height);
          ctx.stroke();
        }
        ctx.restore();
      }

      for (const pt of particles) {
        if (pt.p < 0 || pt.p > 1) continue;
        const f = pt.p * STAGES;
        const x = xAt(pt.p);
        const y = yAt(pt, pt.p, time);
        const size = keyframe(SIZE, Math.min(f, STAGES - 0.001));
        const alpha = keyframe(ALPHA, Math.min(f, STAGES - 0.001));
        const mix = clamp(f / (STAGES - 1)); // 0 raw colour → 1 refined colour

        // Short trail once the data is organised (information and beyond).
        if (f > 1.6) {
          const back = Math.max(0, pt.p - 0.02);
          ctx.strokeStyle = `rgba(${colors.fine},${0.22 * mix})`;
          ctx.lineWidth = Math.max(1, size * 0.45);
          ctx.beginPath();
          ctx.moveTo(xAt(back), yAt(pt, back, time));
          ctx.lineTo(x, y);
          ctx.stroke();
        }

        ctx.fillStyle = `rgba(${mix > 0.55 ? colors.fine : colors.raw},${alpha})`;
        if (f > STAGES - 1.1) {
          ctx.shadowColor = `rgba(${colors.fine},0.9)`;
          ctx.shadowBlur = 12;
        }
        // Square fragments round into dots as they are validated.
        const round = clamp(f / 1.2);
        const angle = (1 - round) * (time * 2 + pt.seed);
        ctx.save();
        ctx.translate(x, y);
        ctx.rotate(angle);
        const half = size / 2;
        ctx.beginPath();
        ctx.roundRect(-half, -half, size, size, half * round);
        ctx.fill();
        ctx.restore();
        ctx.shadowBlur = 0;
      }

      for (const r of ripples) {
        const k = r.t / 1.3;
        ctx.strokeStyle = `rgba(${colors.fine},${0.55 * (1 - k)})`;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(r.x, r.y, 4 + k * 24, 0, Math.PI * 2);
        ctx.stroke();
      }
    };

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      if (!visible || document.hidden) {
        last = 0;
        return;
      }
      const dt = last ? Math.min(0.05, (now - last) / 1000) : 0;
      last = now;
      for (let i = 0; i < particles.length; i++) {
        const pt = particles[i];
        pt.p += pt.speed * dt;
        if (pt.p > 1) {
          if (Math.random() < 0.4) ripples.push({ x: xAt(1) + (rtl ? 6 : -6), y: yAt(pt, 1, now / 1000), t: 0 });
          particles[i] = spawn(false);
        }
      }
      for (let i = ripples.length - 1; i >= 0; i--) {
        ripples[i].t += dt;
        if (ripples[i].t > 1.3) ripples.splice(i, 1);
      }
      draw(now / 1000);
    };

    const start = () => {
      cancelAnimationFrame(raf);
      last = 0;
      if (reduced) draw(0);
      else raf = requestAnimationFrame(frame);
    };

    const onMotionChange = () => {
      reduced = reduceQuery.matches;
      start();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    const intersection = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
    });
    intersection.observe(canvas);
    reduceQuery.addEventListener('change', onMotionChange);
    const colorScheme = window.matchMedia('(prefers-color-scheme: dark)');
    colorScheme.addEventListener('change', resize);

    resize();
    start();
    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
      intersection.disconnect();
      reduceQuery.removeEventListener('change', onMotionChange);
      colorScheme.removeEventListener('change', resize);
      particles = [];
    };
  }, [dir, density, gates]);

  return <canvas ref={ref} className={`flow-canvas ${className}`} aria-hidden="true" />;
}
