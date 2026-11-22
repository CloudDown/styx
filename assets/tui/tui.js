'use strict';

// Hermes Desktop's Nous terminal palette (apps/desktop/src/themes/presets.ts).
const LIGHT = {
  background: '#fefefe', foreground: '#1f2328', cursor: '#0053fd', cursorAccent: '#fefefe',
  selectionBackground: 'rgba(0,83,253,.22)',
  black: '#24292f', red: '#cf222e', green: '#116329', yellow: '#4d2d00',
  blue: '#0969da', magenta: '#8250df', cyan: '#1b7c83', white: '#6e7781',
  brightBlack: '#57606a', brightRed: '#a40e26', brightGreen: '#1a7f37', brightYellow: '#633c01',
  brightBlue: '#218bff', brightMagenta: '#a475f9', brightCyan: '#3192aa', brightWhite: '#8c959f'
};
const DARK = {
  background: '#0d1015', foreground: '#e6edf3', cursor: '#4a84fe', cursorAccent: '#0d1015',
  selectionBackground: 'rgba(74,132,254,.30)',
  black: '#484f58', red: '#ff7b72', green: '#3fb950', yellow: '#d29922',
  blue: '#58a6ff', magenta: '#bc8cff', cyan: '#39c5cf', white: '#b1bac4',
  brightBlack: '#6e7681', brightRed: '#ffa198', brightGreen: '#56d364', brightYellow: '#e3b341',
  brightBlue: '#79c0ff', brightMagenta: '#d2a8ff', brightCyan: '#56d4dd', brightWhite: '#ffffff'
};

const screen = document.getElementById('screen');
const status = document.getElementById('status');
const systemDark = matchMedia('(prefers-color-scheme: dark)');

function darkNow() {
  let choice = '';
  try { choice = localStorage.getItem('styx-fast-appearance') || ''; } catch {}
  if (choice === 'light' || choice === 'dark') return choice === 'dark';
  return systemDark.matches;
}

const term = new Terminal({
  theme: darkNow() ? DARK : LIGHT,
  fontFamily: '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, "DejaVu Sans Mono", monospace',
  fontSize: innerWidth < 600 ? 12 : 13,
  lineHeight: 1.2,
  cursorBlink: true,
  cursorStyle: 'bar',
  scrollback: 4000,
  allowTransparency: false,
  macOptionIsMeta: true,
  rightClickSelectsWord: true,
  smoothScrollDuration: 0
});
const fit = new FitAddon.FitAddon();
term.loadAddon(fit);
term.open(screen);

// Hermes parks its cursor at column 0 while showing a synthetic placeholder.
// Only preview edits in its recognizable, single-row chat prompt. Never write
// predictions into xterm's buffer: the PTY remains the sole source of truth.
const PROMPT = ' ❯ ';
const EDIT_WAIT = 1500;
const simpleChar = /^[A-Za-z0-9À-ÖØ-öø-ÿ .,]$/;
const terminalSurface = screen.querySelector('.xterm-screen');
const terminalRows = terminalSurface.querySelector('.xterm-rows');
const preview = document.createElement('div');
const previewText = document.createTextNode('');
const previewCaret = document.createElement('span');
preview.className = 'styx-typeahead';
preview.hidden = true;
preview.setAttribute('aria-hidden', 'true');
preview.append(previewText, previewCaret);
terminalSurface.append(preview);

let confirmed = null;
let predictions = [];
let blocked = null;
let previewTimer;

function composer() {
  const b = term.buffer.active;
  if (b.type !== 'alternate' || b.viewportY !== b.baseY ||
      !term.modes.bracketedPasteMode || term.modes.insertMode ||
      term.modes.synchronizedOutputMode || document.activeElement !== term.textarea ||
      term.hasSelection()) return null;
  const line = b.getLine(b.baseY + b.cursorY);
  const start = PROMPT.length;
  if (!line || line.isWrapped || line.translateToString(false, 0, start) !== PROMPT ||
      !line.getCell(start - 2)?.isBold()) return null;

  const x = b.cursorX;
  // Leave the right-hand gutter and wrapping to Hermes.
  const limit = term.cols - start - 8;
  if (x === 0) {
    const length = line.translateToString(true).length - start;
    if (length > 0 && length < limit && !line.getCell(start)?.isBgDefault()) {
      return { row: b.cursorY, draft: '', cover: length, limit };
    }
    return null;
  }
  if (x < start || x - start >= limit || line.translateToString(true, x).trimEnd()) return null;
  const draft = line.translateToString(false, start, x);
  // Don't infer selection, double-width cells, completion menus or shell
  // prompts from the screen. In those cases just forward the keystrokes.
  if (draft.length !== x - start || !Array.from(draft).every(c => simpleChar.test(c))) return null;
  return { row: b.cursorY, draft, cover: draft.length, limit };
}

function clearPreview() {
  clearTimeout(previewTimer);
  confirmed = null;
  predictions = [];
  preview.hidden = true;
  previewText.data = '';
}

function paintPreview() {
  const draft = predictions.at(-1);
  // A type/delete pair can be coalesced into an unchanged server frame.
  // Keep the pending edits for reconciliation but don't cover identical text.
  if (draft === confirmed.draft) {
    preview.hidden = true;
    return;
  }
  // xterm sets fractional pixel sizes; use its grid dimensions, not rounded
  // clientWidth/Height. Its live colors can also change via OSC (e.g. OSC 11).
  const cellW = parseFloat(terminalSurface.style.width) / term.cols;
  const cellH = parseFloat(terminalSurface.style.height) / term.rows;
  const theme = term.options.theme;
  const viewportBackground = terminalSurface.parentElement.style.backgroundColor;
  const colors = getComputedStyle(terminalRows);
  Object.assign(preview.style, {
    left: `${PROMPT.length * cellW}px`,
    top: `${confirmed.row * cellH}px`,
    width: `${Math.max(confirmed.cover + 1, draft.length + 1) * cellW}px`,
    height: `${cellH}px`,
    lineHeight: `${cellH}px`,
    backgroundColor: viewportBackground || theme.background,
    color: colors.color,
    fontFamily: colors.fontFamily,
    fontSize: colors.fontSize,
    letterSpacing: colors.letterSpacing
  });
  previewCaret.style.left = `${draft.length * cellW}px`;
  previewCaret.style.backgroundColor = theme.cursor;
  previewText.data = draft;
  preview.hidden = false;
}

function reconcilePreview() {
  if (!confirmed) return;
  const now = composer();
  if (!now || now.row !== confirmed.row) return clearPreview();
  if (now.draft !== confirmed.draft) {
    const index = predictions.indexOf(now.draft);
    if (index === -1) return clearPreview();
    predictions.splice(0, index + 1);
    if (!predictions.length) return clearPreview();
  }
  confirmed = now;
  paintPreview();
}

function previewInput(data) {
  // Terminal-generated focus and query replies are not user edits.
  if (/^\x1b(?:\]|P|\[(?:I|O)$|\[[?>]?[0-9;]+[cRnt]$)/.test(data)) return;
  const now = composer();
  if (blocked) {
    if (performance.now() < blocked.until && (!now || blocked.drafts.has(now.draft))) return;
    blocked = null;
  }
  const previous = predictions.at(-1) ?? now?.draft ?? '';
  const next = data === '\x7f' && previous ? previous.slice(0, -1)
    : simpleChar.test(data) ? previous + data : null;
  if (!now || next === null || next.length >= now.limit ||
      predictions.length >= 64 || (confirmed && now.row !== confirmed.row)) {
    if (now) {
      blocked = { until: performance.now() + EDIT_WAIT, drafts: new Set([now.draft, ...predictions]) };
    }
    clearPreview();
    return;
  }
  confirmed ??= now;
  predictions.push(next);
  paintPreview();
  clearTimeout(previewTimer);
  previewTimer = setTimeout(clearPreview, EDIT_WAIT);
}

term.onRender(reconcilePreview);
term.onSelectionChange(clearPreview);
term.textarea.addEventListener('blur', clearPreview);
screen.addEventListener('pointerdown', clearPreview, {capture: true});

let socket = null;
let lastSize = '';
let failed = false;

function say(text, retry) {
  status.textContent = text;
  status.dataset.tap = String(retry);
  status.hidden = false;
}

function ready() {
  if (status.hidden) return;
  status.hidden = true;
  status.dataset.tap = 'false';
}

// Fit, then tell the host only when the grid actually changed: a resize frame
// per pixel would make the TUI redraw for nothing.
function size() {
  try { fit.fit(); } catch {}
  const next = term.cols + 'x' + term.rows;
  if (next === lastSize) return;
  clearPreview();
  lastSize = next;
  if (socket && socket.readyState === 1) {
    socket.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }));
  }
}

function connect() {
  clearPreview();
  blocked = null;
  failed = false;
  if (socket) { socket.onclose = null; socket.close(); }
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  socket = new WebSocket(`${scheme}://${location.host}/_styx/tui/ws`);
  socket.binaryType = 'arraybuffer';
  socket.onopen = () => {
    ready();
    lastSize = '';
    size();
    term.focus();
  };
  socket.onmessage = event => {
    ready();
    term.write(typeof event.data === 'string' ? event.data : new Uint8Array(event.data));
  };
  socket.onclose = event => {
    clearPreview();
    if (event.code === 4401) {
      failed = true;
      say('Session expired — reload to sign in again.', false);
      return;
    }
    say(failed ? 'Disconnected — tap to reconnect' : 'Terminal closed — tap to reopen', true);
  };
}

term.onData(data => {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(data);
    previewInput(data);
  }
});

status.addEventListener('click', () => { if (status.dataset.tap === 'true') connect(); });

new ResizeObserver(size).observe(screen);
window.visualViewport?.addEventListener('resize', size);
window.addEventListener('orientationchange', () => setTimeout(size, 120));

function repaintTheme() {
  term.options.theme = darkNow() ? DARK : LIGHT;
  clearPreview();
  for (const meta of document.querySelectorAll('meta[name="theme-color"]')) {
    meta.content = darkNow() ? '#0d1015' : '#fefefe';
  }
  size();
}
systemDark.addEventListener('change', repaintTheme);
try {
  new BroadcastChannel('styx-appearance').onmessage = repaintTheme;
} catch {}

window.addEventListener('pagehide', () => {
  clearPreview();
  if (socket) { socket.onclose = null; socket.close(); }
});

requestAnimationFrame(() => { size(); connect(); });
