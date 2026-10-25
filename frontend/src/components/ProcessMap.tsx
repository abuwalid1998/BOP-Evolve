import { useEffect, useRef, type ReactNode } from 'react';

/**
 * Animated process map. Each step is an HTML card laid out by CSS (a serpentine grid
 * that also mirrors in RTL and stacks on narrow screens); a canvas behind the cards
 * draws the connectors and moves "case" tokens from step to step. At decision steps a
 * token can leave the main path through an exit (quarantined, no exception, dismissed),
 * with probabilities taken from live counts. Token colour shows what the record has
 * become: raw record, validated case, finding, confirmed finding, learning evidence.
 *
 * Honors prefers-reduced-motion (connectors and a static sample of tokens only) and
 * pauses while the tab is hidden.
 */

export type TokenState = 'raw' | 'trusted' | 'flagged' | 'confirmed' | 'learned';

export interface MapStep {
  id: string;
  /** State a token takes on after leaving this step on the main path. */
  becomes: TokenState;
  /** Optional exit: probability of leaving the flow here, and the exit's element id. */
  exit?: { id: string; probability: number };
}

export interface ProcessMapProps {
  steps: MapStep[];
  /** Renders the cards. Every step and exit must render an element with data-node={id}. */
  children: ReactNode;
  /** Step to emphasise (tour or selection); a highlighted example token is sent to it. */
  focus?: number | null;
  /** Tokens spawned per second. */
  rate?: number;
  className?: string;
}

interface Token {
  seg: number; // index of the step the token is travelling *from*
  t: number; // 0..1 along the current segment
  state: TokenState;
  exiting: { from: { x: number; y: number }; to: { x: number; y: number } } | null;
  fade: number;
  speed: number; // px per second
  example?: boolean;
}

interface Point {
  x: number;
  y: number;
}

const COLOURS: Record<TokenState | 'exit', string> = {
  raw: '--text-3',
  trusted: '--info',
  flagged: '--warn',
  confirmed: '--brand',
  learned: '--ok',
  exit: '--border-strong',
};

function cssColour(el: Element, name: string, fallback: string) {
  return getComputedStyle(el).getPropertyValue(name).trim() || fallback;
}

export function ProcessMap({ steps, children, focus = null, rate = 1.6, className = '' }: ProcessMapProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stepsRef = useRef(steps);
  stepsRef.current = steps;
  const focusRef = useRef<number | null>(focus);
  const exampleRef = useRef<Token | null>(null);

  useEffect(() => {
    focusRef.current = focus;
    if (focus === null) {
      exampleRef.current = null;
      return;
    }
    // Restart the example token from the first step whenever the focus moves back.
    const ex = exampleRef.current;
    if (!ex || ex.seg > focus) {
      exampleRef.current = { seg: 0, t: 0, state: 'raw', exiting: null, fade: 1, speed: 260, example: true };
    }
  }, [focus]);

  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let centres: Point[] = [];
    let exits: Record<string, Point> = {};
    let colours: Record<string, string> = {};
    let width = 0;
    let height = 0;

    const measure = () => {
      const box = wrap.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      if (box.width !== width || box.height !== height || canvas.width !== Math.round(box.width * dpr)) {
        width = box.width;
        height = box.height;
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }
      const centre = (id: string): Point | null => {
        const el = wrap.querySelector(`[data-node="${id}"]`);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return { x: r.left - box.left + r.width / 2, y: r.top - box.top + r.height / 2 };
      };
      centres = stepsRef.current.map((s) => centre(s.id) ?? { x: 0, y: 0 });
      exits = {};
      for (const s of stepsRef.current) {
        if (s.exit) exits[s.exit.id] = centre(s.exit.id) ?? centres[0];
      }
      colours = Object.fromEntries(
        Object.entries(COLOURS).map(([k, v]) => [k, cssColour(wrap, v, '#888')]),
      );
      colours.line = cssColour(wrap, '--border-strong', '#ccc');
      colours.focus = cssColour(wrap, '--brand', '#9e1153');
    };

    const observer = new ResizeObserver(measure);
    observer.observe(wrap);
    measure();

    const tokens: Token[] = [];
    let spawnDebt = 0;
    let last = performance.now();
    let frame = 0;
    let running = true;
    let sinceMeasure = 0;

    const segLength = (i: number) => {
      const a = centres[i];
      const b = centres[i + 1];
      return a && b ? Math.hypot(b.x - a.x, b.y - a.y) || 1 : 1;
    };

    const position = (tok: Token): Point => {
      if (tok.exiting) {
        const { from, to } = tok.exiting;
        return { x: from.x + (to.x - from.x) * tok.t, y: from.y + (to.y - from.y) * tok.t };
      }
      const a = centres[tok.seg];
      const b = centres[tok.seg + 1] ?? a;
      return { x: a.x + (b.x - a.x) * tok.t, y: a.y + (b.y - a.y) * tok.t };
    };

    // A token arrives at step `index`: it may exit there, otherwise it takes on the step's state.
    const arrive = (tok: Token, index: number): boolean => {
      const step = stepsRef.current[index];
      if (!tok.example && step.exit && Math.random() < step.exit.probability) {
        tok.exiting = { from: centres[index], to: exits[step.exit.id] ?? centres[index] };
        tok.t = 0;
        return true;
      }
      tok.state = step.becomes;
      return false;
    };

    const drawConnectors = () => {
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 6]);
      ctx.strokeStyle = colours.line;
      ctx.beginPath();
      centres.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
      ctx.stroke();
      ctx.setLineDash([2, 5]);
      stepsRef.current.forEach((s, i) => {
        if (!s.exit) return;
        const to = exits[s.exit.id];
        if (!to) return;
        ctx.beginPath();
        ctx.moveTo(centres[i].x, centres[i].y);
        ctx.lineTo(to.x, to.y);
        ctx.stroke();
      });
      ctx.setLineDash([]);
    };

    const drawToken = (tok: Token) => {
      const p = position(tok);
      const colour = tok.exiting ? colours.exit : colours[tok.state];
      ctx.globalAlpha = tok.fade;
      if (tok.example) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 11, 0, Math.PI * 2);
        ctx.strokeStyle = colours.focus;
        ctx.lineWidth = 2;
        ctx.stroke();
      }
      ctx.beginPath();
      ctx.arc(p.x, p.y, tok.example ? 6.5 : 4.5, 0, Math.PI * 2);
      ctx.fillStyle = colour;
      ctx.fill();
      ctx.globalAlpha = 1;
    };

    const advance = (tok: Token, dt: number): boolean => {
      if (tok.exiting) {
        const dist = Math.hypot(tok.exiting.to.x - tok.exiting.from.x, tok.exiting.to.y - tok.exiting.from.y) || 1;
        tok.t += (tok.speed * 0.7 * dt) / dist;
        if (tok.t >= 1) {
          tok.t = 1;
          tok.fade -= dt * 1.6;
        }
        return tok.fade > 0;
      }
      const end = centres.length - 1;
      if (tok.seg >= end) {
        tok.fade -= dt * 1.4;
        return tok.fade > 0;
      }
      if (tok.example && focusRef.current !== null && tok.seg >= focusRef.current) return true; // wait at the focus
      tok.t += (tok.speed * dt) / segLength(tok.seg);
      while (tok.t >= 1 && !tok.exiting) {
        tok.t -= 1;
        tok.seg += 1;
        if (arrive(tok, tok.seg)) break;
        if (tok.seg >= end) {
          tok.t = 0;
          break;
        }
        if (tok.example && focusRef.current !== null && tok.seg >= focusRef.current) {
          tok.t = 0;
          break;
        }
      }
      return true;
    };

    const render = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      // Cards can reflow without the wrapper resizing (fonts, live numbers), so re-measure now and then.
      sinceMeasure += dt;
      if (sinceMeasure > 0.75) {
        sinceMeasure = 0;
        measure();
      }
      ctx.clearRect(0, 0, width, height);
      drawConnectors();
      spawnDebt += dt * rate;
      while (spawnDebt >= 1 && tokens.length < 80) {
        spawnDebt -= 1;
        tokens.push({ seg: 0, t: 0, state: 'raw', exiting: null, fade: 1, speed: 70 + Math.random() * 50 });
      }
      for (let i = tokens.length - 1; i >= 0; i--) {
        if (!advance(tokens[i], dt)) tokens.splice(i, 1);
        else drawToken(tokens[i]);
      }
      const ex = exampleRef.current;
      if (ex) {
        advance(ex, dt);
        drawToken(ex);
      }
      if (running) frame = requestAnimationFrame(render);
    };

    const drawStatic = () => {
      measure();
      ctx.clearRect(0, 0, width, height);
      drawConnectors();
      const states: TokenState[] = stepsRef.current.map((s) => s.becomes);
      for (let i = 0; i < centres.length - 1; i++) {
        drawToken({ seg: i, t: 0.5, state: states[i], exiting: null, fade: 1, speed: 0 });
      }
    };

    const onVisibility = () => {
      if (reduced) return;
      if (document.hidden) {
        running = false;
        cancelAnimationFrame(frame);
      } else if (!running) {
        running = true;
        last = performance.now();
        frame = requestAnimationFrame(render);
      }
    };

    if (reduced) {
      drawStatic();
      observer.disconnect();
      const ro = new ResizeObserver(drawStatic);
      ro.observe(wrap);
      return () => ro.disconnect();
    }
    frame = requestAnimationFrame(render);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      running = false;
      cancelAnimationFrame(frame);
      observer.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [rate]);

  return (
    <div ref={wrapRef} className={`process-map ${className}`}>
      <canvas ref={canvasRef} className="process-map-canvas" aria-hidden="true" />
      {children}
    </div>
  );
}
