import { useEffect, useRef } from 'react';

// Design tokens (match CSS custom properties)
const C_BG      = '#0A0A0B';
const C_SURFACE = '#111114';
const C_BORDER  = 'rgba(255,255,255,0.09)';
const C_MUT     = '#475569';
const C_GREEN   = '#22C55E';
const C_AMBER   = '#F59E0B';
const C_RED     = '#EF4444';
const C_ACCENT  = '#6366F1';

const NUM_BLOCKS    = 10;
const LOOP_MS       = 12000;
const BLK_MS        = LOOP_MS / NUM_BLOCKS; // 1200ms per block
const FLAGGED_IDX   = 7;   // appears at t≈8.4s (~70% through loop)

const BW  = 74;   // block width  (px)
const BH  = 84;   // block height (px)
const SP  = 110;  // center-to-center spacing
const VIG = 64;   // vignette fade width

// Block content — idx 7 is the injected/flagged block
const CHAIN = [
  { hash: '3f9a4b', score: 94 },
  { hash: 'e12bc7', score: 88 },
  { hash: 'a7c4d2', score: 92 },
  { hash: '8d1fe0', score: 96 },
  { hash: '4b23a9', score: 91 },
  { hash: '9e5a3c', score: 89 },
  { hash: '2c789f', score: 93 },
  { hash: 'ff0211', score: 11 }, // FLAGGED = index 7
  { hash: '7a3d54', score: 87 },
  { hash: '1b6e80', score: 95 },
];

function easeOut3(t) {
  const c = Math.max(0, Math.min(1, t));
  return 1 - (1 - c) * (1 - c) * (1 - c);
}

// blockIdx for a given absolute block number (handles negative modulo)
function bIdx(bn) { return ((bn % NUM_BLOCKS) + NUM_BLOCKS) % NUM_BLOCKS; }

// Effective center-x of block bn, including birth-snap offset
function cx(bn, blockIndex, anchor) {
  const slotT = Math.max(blockIndex - bn, 0);
  const birth = slotT < 0.22 ? SP * 0.38 * (1 - easeOut3(slotT / 0.22)) : 0;
  return anchor + SP * (bn - blockIndex) + birth;
}

// Rounded rectangle path helper
function rrect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.arcTo(x + w, y,     x + w, y + r,     r);
  ctx.lineTo(x + w, y + h - r);
  ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
  ctx.lineTo(x + r, y + h);
  ctx.arcTo(x,     y + h, x,     y + h - r, r);
  ctx.lineTo(x, y + r);
  ctx.arcTo(x,     y,     x + r, y,         r);
  ctx.closePath();
}

function drawHexSeal(ctx, x, y, r, flagged) {
  ctx.save();
  ctx.strokeStyle = flagged ? 'rgba(239,68,68,0.55)' : 'rgba(99,102,241,0.50)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i < 6; i++) {
    const a = (Math.PI / 3) * i - Math.PI / 6;
    i === 0
      ? ctx.moveTo(x + r * Math.cos(a), y + r * Math.sin(a))
      : ctx.lineTo(x + r * Math.cos(a), y + r * Math.sin(a));
  }
  ctx.closePath();
  ctx.stroke();
  ctx.restore();
}

function drawThread(ctx, x1, x2, cy, slotT, flagged) {
  const progress = Math.min(easeOut3(slotT * 4.0), 1.0);
  if (progress < 0.01) return;
  const ex1 = x1 + BW / 2;
  const ex2 = x2 - BW / 2;
  const drawTo = ex1 + (ex2 - ex1) * progress;
  ctx.save();
  ctx.strokeStyle = flagged ? 'rgba(239,68,68,0.38)' : 'rgba(255,255,255,0.10)';
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 5]);
  ctx.beginPath();
  ctx.moveTo(ex1, cy);
  ctx.lineTo(drawTo, cy);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.restore();
}

function drawBlockFull(ctx, centerX, centerY, slotT, blockIdx, flagged, alpha) {
  const blk  = CHAIN[blockIdx];
  const bx   = centerX - BW / 2;
  const by   = centerY - BH / 2;

  // Y-jitter on flagged arrival
  let dy = 0;
  if (flagged && slotT < 0.30) {
    dy = 6 * (1 - easeOut3(slotT / 0.30)) * Math.sin(slotT * Math.PI * 9);
  }
  const ry = by + dy;

  ctx.save();
  ctx.globalAlpha = Math.max(0, Math.min(1, alpha));

  // Glow post-scan on flagged
  if (flagged && slotT > 0.58) {
    ctx.shadowColor   = C_RED;
    ctx.shadowBlur    = 16 * Math.min((slotT - 0.58) / 0.30, 1.0);
  }

  // Fill
  ctx.fillStyle = flagged ? 'rgba(239,68,68,0.07)' : C_SURFACE;
  rrect(ctx, bx, ry, BW, BH, 7);
  ctx.fill();
  ctx.shadowBlur = 0;

  // Border
  ctx.strokeStyle = flagged ? 'rgba(239,68,68,0.55)' : C_BORDER;
  ctx.lineWidth   = flagged ? 1.5 : 1;
  rrect(ctx, bx, ry, BW, BH, 7);
  ctx.stroke();

  // Scan line sweep (flagged only)
  if (flagged && slotT >= 0.18 && slotT <= 0.62) {
    const sp = (slotT - 0.18) / 0.44;
    ctx.fillStyle = 'rgba(239,68,68,0.12)';
    ctx.fillRect(bx, ry, BW, sp * BH);
    ctx.strokeStyle = 'rgba(239,68,68,0.75)';
    ctx.lineWidth   = 1.5;
    ctx.beginPath();
    ctx.moveTo(bx,      ry + sp * BH);
    ctx.lineTo(bx + BW, ry + sp * BH);
    ctx.stroke();
  }

  // Flash burst (flagged only)
  if (flagged && slotT >= 0.62 && slotT <= 0.82) {
    const ft = (slotT - 0.62) / 0.20;
    ctx.fillStyle = `rgba(239,68,68,${(1 - ft) * 0.28})`;
    rrect(ctx, bx - 5, ry - 5, BW + 10, BH + 10, 11);
    ctx.fill();
  }

  // Hash label
  ctx.font          = '10px JetBrains Mono, Fira Code, monospace';
  ctx.textAlign     = 'center';
  ctx.textBaseline  = 'top';
  ctx.fillStyle     = flagged ? 'rgba(239,68,68,0.65)' : C_MUT;
  ctx.fillText(`#${blk.hash}`, centerX, ry + 9);

  // Trust score
  const scoreColor = blk.score >= 80 ? C_GREEN : blk.score >= 55 ? C_AMBER : C_RED;
  ctx.font         = '700 22px Inter, system-ui, sans-serif';
  ctx.textBaseline = 'middle';
  ctx.fillStyle    = scoreColor;
  ctx.fillText(String(blk.score), centerX, ry + BH / 2 - 4);

  // "trust" sub-label
  ctx.font         = '400 9px Inter, system-ui, sans-serif';
  ctx.textBaseline = 'top';
  ctx.fillStyle    = C_MUT;
  ctx.fillText('trust', centerX, ry + BH / 2 + 8);

  // Seal glyph fades in when block is settled
  if (slotT > 0.45) {
    const sealAlpha = Math.min((slotT - 0.45) / 0.25, 1.0);
    ctx.globalAlpha = alpha * sealAlpha;
    drawHexSeal(ctx, centerX, ry + BH - 13, 6, flagged);
  }

  ctx.globalAlpha = alpha;

  // "behavioral break detected" label (above block, flagged only)
  if (flagged && slotT >= 0.68) {
    const lAlpha = Math.min((slotT - 0.68) / 0.18, 1.0);
    ctx.globalAlpha = alpha * lAlpha;
    ctx.font         = '600 9px JetBrains Mono, Fira Code, monospace';
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'bottom';
    ctx.fillStyle    = C_RED;
    ctx.fillText('behavioral break detected', centerX, ry - 10);
    ctx.font      = '400 8px Inter, system-ui, sans-serif';
    ctx.fillStyle = C_MUT;
    ctx.fillText('decision: review', centerX, ry - 1);
  }

  ctx.restore();
}

function applyVignette(ctx, W, H) {
  const gl = ctx.createLinearGradient(0, 0, VIG, 0);
  gl.addColorStop(0, C_BG);
  gl.addColorStop(1, 'rgba(10,10,11,0)');
  ctx.fillStyle = gl;
  ctx.fillRect(0, 0, VIG, H);

  const gr = ctx.createLinearGradient(W, 0, W - VIG, 0);
  gr.addColorStop(0, C_BG);
  gr.addColorStop(1, 'rgba(10,10,11,0)');
  ctx.fillStyle = gr;
  ctx.fillRect(W - VIG, 0, VIG, H);
}

function renderScene(ctx, W, H, elapsed) {
  ctx.fillStyle = C_BG;
  ctx.fillRect(0, 0, W, H);

  const blockIndex = elapsed / BLK_MS;
  // Rightmost visible block center sits just inside the right vignette
  const anchor = W - VIG - BW / 2 - 2;
  const midY   = H / 2;

  const lo = Math.floor(blockIndex) - 5;
  const hi = Math.ceil(blockIndex)  + 1;

  // Pass 1: threads (drawn behind blocks)
  for (let bn = lo; bn <= hi; bn++) {
    const pcx = cx(bn - 1, blockIndex, anchor);
    const ncx = cx(bn,     blockIndex, anchor);
    if (ncx + BW < 0 || pcx - BW > W) continue;
    const slotT   = Math.max(blockIndex - bn, 0);
    const flagged = bIdx(bn) === FLAGGED_IDX;
    drawThread(ctx, pcx, ncx, midY, slotT, flagged);
  }

  // Pass 2: blocks
  for (let bn = lo; bn <= hi; bn++) {
    const bcx   = cx(bn, blockIndex, anchor);
    if (bcx + BW < -10 || bcx - BW > W + 10) continue;
    const slotT   = Math.max(blockIndex - bn, 0);
    const flagged = bIdx(bn) === FLAGGED_IDX;
    const alpha   = Math.min(slotT / 0.12, 1.0);
    drawBlockFull(ctx, bcx, midY, slotT, bIdx(bn), flagged, alpha);
  }

  applyVignette(ctx, W, H);
}

// ─── React component ────────────────────────────────────────────────────────

export default function ReceiptChainHero() {
  const canvasRef = useRef(null);
  const stateRef  = useRef({ paused: true, isVis: false, rafId: null, t0: null });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const st  = stateRef.current;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    function setSize() {
      const parent = canvas.parentElement;
      if (!parent) return;
      const W = parent.clientWidth  || 480;
      const H = parent.clientHeight || 296;
      canvas.width  = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      canvas.style.width  = W + 'px';
      canvas.style.height = H + 'px';
    }
    setSize();

    const ctx = canvas.getContext('2d');

    // Static frame for prefers-reduced-motion
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      renderScene(ctx, canvas.width / dpr, canvas.height / dpr, BLK_MS * 5.5);
      return;
    }

    function tick(now) {
      if (st.paused) return;
      if (st.t0 === null) st.t0 = now;
      const elapsed = (now - st.t0) % LOOP_MS;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      renderScene(ctx, canvas.width / dpr, canvas.height / dpr, elapsed);
      st.rafId = requestAnimationFrame(tick);
    }

    function play() {
      if (!st.paused) return;
      st.paused = false;
      st.rafId  = requestAnimationFrame(tick);
    }

    function pause() {
      st.paused = true;
      if (st.rafId) { cancelAnimationFrame(st.rafId); st.rafId = null; }
    }

    function sync() {
      st.isVis && !document.hidden ? play() : pause();
    }

    const obs = new IntersectionObserver(
      ([e]) => { st.isVis = e.isIntersecting; sync(); },
      { threshold: 0.1 }
    );
    obs.observe(canvas);

    document.addEventListener('visibilitychange', sync);

    const ro = new ResizeObserver(setSize);
    ro.observe(canvas.parentElement);

    return () => {
      pause();
      obs.disconnect();
      ro.disconnect();
      document.removeEventListener('visibilitychange', sync);
    };
  }, []);

  return (
    <div
      className="receipt-chain-hero"
      aria-label="Animated receipt chain — behavioral break detection visualization"
    >
      <div className="rch-header">
        <span className="rch-label">Receipt Chain</span>
        <span className="rch-live">
          <span className="dot" aria-hidden="true" />
          LIVE
        </span>
      </div>
      <div className="rch-body">
        <canvas ref={canvasRef} aria-hidden="true" />
      </div>
    </div>
  );
}
