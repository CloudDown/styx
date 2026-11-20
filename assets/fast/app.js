'use strict';

// Hermes owns the data and execution. This tab keeps only in-memory view state.
const $ = id => document.getElementById(id);
const FAST = '/_styx/fast';
const key = `hermes.webapp.session.v1:${JSON.stringify([location.origin, ''])}`;
const profile = new URLSearchParams(location.search).get('profile');
const scoped = (path, params = {}) => {
  const url = new URL(path, location.origin);
  for (const [name, value] of Object.entries(params)) url.searchParams.set(name, value);
  if (profile) url.searchParams.set('profile', profile);
  return url.pathname + url.search;
};
const ui = {
  sessions: $('sessions'), messages: $('messages'), prompt: $('prompt'), model: $('model'),
  notice: $('notice'), send: $('send'), stop: $('stop'), history: $('history'),
};
const composer = $('composer');
const PAGE = 30;
let token, authorized = false, selection = null, rows = [], total = 0, listing = false;
let loaded = 0, historyOffset = 0, historyLoad = 0, reading = false;
let modelChoice = null, models = null, fetchingModels = false, turn = null;
let link = null, linkTimer = 0, linkPromise = null;
let defaultModel = null, editRow = null, writing = false, deleting = false;
const mutations = new Map();

const uid = () => Array.from(crypto.getRandomValues(new Uint8Array(16)),
  b => (b + 256).toString(16).slice(1)).join('');
const node = (tag, text, className) => {
  const el = document.createElement(tag);
  if (text) el.textContent = text;
  if (className) el.className = className;
  return el;
};
const text = value => typeof value === 'string' ? value : Array.isArray(value)
  ? value.filter(part => part?.type === 'text' && typeof part.text === 'string').map(part => part.text).join('\n')
  : '';
const bottom = () => { ui.history.scrollTop = ui.history.scrollHeight; syncLatest(); };
const atBottom = () => ui.history.scrollHeight - ui.history.scrollTop - ui.history.clientHeight < 100;
// Show the “back to the live end” affordance only once the reader has really
// left the tail — never as a permanent decoration over the thread.
const syncLatest = () => { $('latest').hidden = atBottom(); };
const titleFor = row => row?.title || row?.root_title || 'Untitled chat';
const signIn = scoped(FAST + '/connect');
// The official launcher returns to / with a one-use Styx entry marker. The
// authenticated shell is served there directly; reloads use its stable URL.
if (location.pathname !== FAST) window.history.replaceState(null, '', scoped(FAST));
$('reconnect').href = signIn;
$('official').href = scoped('/', { _styx_view: 'hermes' });
$('official').target = '_blank';
$('official').rel = 'noopener noreferrer';

function notice(message = '', error = false) {
  ui.notice.textContent = message;
  ui.notice.dataset.error = String(error);
}

function controls() {
  ui.send.disabled = !authorized || !!turn || reading || writing || audioBusy || !!recording
    || !(ui.prompt.value.trim() || attachments.length);
  ui.prompt.readOnly = !authorized;
  ui.model.disabled = !authorized || !!turn;
  $('new').disabled = !!turn;
  for (const button of ui.sessions.querySelectorAll('button')) button.disabled = !!turn;
  ui.stop.hidden = !turn?.admission;
  ui.send.hidden = !ui.stop.hidden;
  ui.stop.disabled = !!turn?.stopping;
  $('rename-active').hidden = !selection;
  $('rename-active').disabled = $('attach').disabled = !authorized || !!turn || writing;
  $('effort').disabled = !authorized || !!turn || writing;
  for (const id of ['dictate','voice']) $(id).disabled = !canRecord || !authorized || !!turn || audioBusy
    || (!!recording && recording.button.id !== id);
  for (const button of $('attachments').querySelectorAll('button')) button.disabled = !!turn;
}

function unauthorized() {
  mutations.clear();
  closeLink();
  for (const id of ['effort-menu','model-dialog']) $(id).hidePopover();
  $('session-dialog').close();
  editRow = defaultModel = null;
  clearComposerMedia();
  authorized = false;
  try { sessionStorage.removeItem(key); } catch {}
  rows = [];
  loaded = total = 0;
  selection = null;
  models = modelChoice = null;
  effortChoice = undefined;
  updateEffort();
  ui.prompt.value = '';
  $('title').textContent = 'New chat';
  ui.model.textContent = 'Default model';
  drawSessions();
  ui.messages.replaceChildren();
  $('welcome').hidden = false;
  $('older').hidden = true;
  $('session-status').textContent = 'Disconnected';
  $('reconnect').hidden = false;
  notice('Your sign-in has ended. Reconnect to continue.', true);
  controls();
}

async function api(path, method = 'GET', payload, timeout = 35000) {
  const form = payload instanceof FormData;
  const result = await fetch(path, {
    method, credentials: 'same-origin', redirect: 'manual', cache: 'no-store',
    headers: { 'X-Hermes-Session-Token': token, ...(payload && !form && {'Content-Type':'application/json'}) },
    body: form ? payload : payload && JSON.stringify(payload),
    signal: AbortSignal.timeout(timeout),
  });
  if (result.type === 'opaqueredirect' || result.status === 401) {
    unauthorized();
    throw new Error('Sign-in required.');
  }
  if (!result.ok) throw Object.assign(new Error(`Hermes request failed (${result.status}).`), {status:result.status});
  return result.json();
}

function drawSessions() {
  const fragment = document.createDocumentFragment();
  for (const row of rows) {
    const li = node('li');
    const button = node('button');
    button.append(node('span', titleFor(row)));
    button.type = 'button';
    button.title = button.textContent;
    button.disabled = !!turn;
    if (selection?.id === row.id) button.setAttribute('aria-current', 'true');
    button.addEventListener('click', () => selection?.id === row.id ? sessionsOpen(false) : select(row));
    button.addEventListener('dblclick', () => editSession(false,row));
    button.addEventListener('keydown', e => { if (e.key === 'F2') { e.preventDefault(); editSession(false,row); } });
    const actions = node('button', '', 'row-actions danger');
    const icon = document.createElementNS('http://www.w3.org/2000/svg','svg');
    icon.setAttribute('viewBox','0 0 24 24');
    icon.setAttribute('aria-hidden','true');
    const path = document.createElementNS(icon.namespaceURI,'path');
    path.setAttribute('d','M4 7h16m-10 4v6m4-6v6M6 7l1 14h10l1-14M9 7V4h6v3');
    icon.append(path); actions.append(icon);
    actions.type = 'button';
    actions.disabled = !!turn;
    actions.setAttribute('aria-label', `Delete: ${titleFor(row)}`);
    actions.title = 'Delete session';
    actions.addEventListener('click', () => editSession(true,row));
    li.append(button, actions);
    fragment.append(li);
  }
  ui.sessions.replaceChildren(fragment);
  $('more').hidden = !authorized || loaded >= total;
}

async function listSessions(reset = false) {
  if (listing) return;
  listing = true;
  $('more').disabled = true;
  $('refresh').hidden = true;
  try {
    const offset = reset ? 0 : loaded;
    const value = await api(scoped('/api/sessions', { limit: PAGE, offset, order: 'recent', exclude_sources: 'cron' }));
    if (!Array.isArray(value.sessions) || !Number.isInteger(value.total)) throw new Error();
    if (Object.values(value.storage || {}).includes('corrupt')) throw new Error();
    const page = value.sessions.filter(row => typeof row?.id === 'string');
    rows = reset ? page : [...new Map([...rows, ...page].map(row => [row.id, row])).values()];
    total = value.total;
    loaded = value.sessions.length ? offset + value.sessions.length : total;
    authorized = true;
    $('session-status').textContent = rows.length ? '' : 'No conversations yet.';
    drawSessions();
    // Warm the viewer socket so the first message does not pay the connect.
    void ensureLink().catch(() => {});
  } catch {
    if ($('reconnect').hidden) {
      $('session-status').textContent = 'Could not load sessions.';
      $('refresh').hidden = false;
    }
  } finally {
    listing = false;
    $('more').disabled = false;
    controls();
  }
}

function message(role, content) {
  const li = node('li', '', 'message ' + role);
  const body = node(role === 'user' ? 'p' : 'div', '', role === 'assistant' ? 'prose' : '');
  body.dir = 'auto';
  li.append(node('span', role === 'user' ? 'You' : 'Hermes', 'sr-only'), body);
  if (role === 'assistant' && content) renderReply(body, content);
  else body.textContent = content;
  return li;
}

async function loadHistory(older = false) {
  if (!selection) return;
  const request = ++historyLoad;
  const id = selection.id;
  const offset = older ? historyOffset : 0;
  reading = true;
  controls();
  $('older').disabled = true;
  notice(older ? 'Loading earlier messages…' : 'Loading conversation…');
  try {
    const data = await api(scoped(`/api/sessions/${encodeURIComponent(id)}/messages`,
      { limit: PAGE, offset, order: 'latest', include_compacted: 'true', inline_images: 'false' }));
    if (request !== historyLoad) return;
    const fragment = document.createDocumentFragment();
    for (const row of data.messages) {
      const content = text(row.content);
      if (['user', 'assistant'].includes(row.role) && row.display_kind !== 'hidden' && content) {
        fragment.append(message(row.role, content));
      }
    }
    if (older) {
      const height = ui.history.scrollHeight, scroll = ui.history.scrollTop;
      ui.messages.prepend(fragment);
      ui.history.scrollTop = scroll + ui.history.scrollHeight - height;
    } else {
      ui.messages.replaceChildren(fragment);
      bottom();
    }
    const count = data.pagination?.returned ?? data.messages.length;
    historyOffset = offset + count;
    $('older').hidden = count < PAGE;
    notice(ui.messages.childElementCount ? '' : 'No text messages in this conversation.');
  } catch (error) {
    if (request === historyLoad && authorized) notice(error.message || 'Could not load this conversation.', true);
  } finally {
    if (request === historyLoad) {
      reading = false;
      controls();
      $('older').disabled = false;
    }
  }
}

function sessionsOpen(open) {
  $('workspace').dataset.sessions = String(open);
  $('open-sessions').setAttribute('aria-expanded', String(open));
  if (matchMedia('(max-width: 680px)').matches) (open ? $('close-sessions') : $('open-sessions')).focus();
}

function select(row) {
  if (turn) return;
  clearComposerMedia();
  ++historyLoad;
  reading = false;
  selection = row;
  modelChoice = null;
  effortChoice = undefined;
  updateEffort();
  ui.messages.replaceChildren();
  $('welcome').hidden = !!row;
  $('older').hidden = true;
  $('title').textContent = row ? titleFor(row) : 'New chat';
  updateModelLabel();
  ui.prompt.placeholder = row ? 'Send a follow-up' : 'What are we building?';
  ui.prompt.value = '';
  fitInput();
  notice();
  sessionsOpen(false);
  drawSessions();
  controls();
  if (row) void loadHistory();
}

class RpcError extends Error {}

// One viewer socket, kept open like Desktop's: a per-message WebSocket made
// every send start on a cold connect. It idles out after 15 quiet minutes,
// closes with the page, and reconnects transparently when the gateway drops it.
function closeLink() {
  const state = link;
  link = null;
  clearTimeout(linkTimer);
  if (!state) return;
  for (const call of state.pending.values()) call.reject(new Error('Hermes connection closed.'));
  state.pending.clear();
  try { state.socket?.close(); } catch {}
}

function idleLink() {
  clearTimeout(linkTimer);
  linkTimer = setTimeout(() => { if (!turn) closeLink(); }, 15 * 60 * 1000);
}

function routeEvent(frame) {
  const current = turn;
  if (!current || !frame) return;
  // Events can beat the submit receipt; the turn replays them once admitted.
  if (!current.admission && current.sent) {
    if (current.frames.length < 256) current.frames.push(frame);
    return;
  }
  event(current, frame);
}

async function rpc(method, params) {
  return (await ensureLink()).rpc(method, params);
}

async function ensureLink() {
  if (link?.socket?.readyState === WebSocket.OPEN) { idleLink(); return link; }
  // One cold open at a time: the warm-up after listing and a first send can race.
  if (linkPromise) return linkPromise;
  linkPromise = openLink().finally(() => { linkPromise = null; });
  return linkPromise;
}

async function openLink() {
  const { ticket } = await api(scoped('/api/webapp/socket-ticket', { socket: 'gateway' }), 'POST');
  if (!/^[\w-]{20,200}$/.test(ticket || '')) throw new Error('Hermes did not return a socket ticket.');
  const address = new URL(scoped('/api/ws', { native_dial: 'browser' }), location.origin);
  address.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const socket = new WebSocket(address, ['hermes-gateway-v1', `hermes-gateway-ticket.${ticket}`]);
  const state = { socket, pending: new Map(), open: false };
  link = state;
  socket.addEventListener('message', ({ data }) => {
    let frame;
    try { frame = JSON.parse(data); } catch { return; }
    if (frame?.method === 'event') { routeEvent(frame.params); return; }
    if (frame?.method && frame.id != null) {
      // Do not auto-approve actions or answer prompts. The full UI can resume this session.
      if (turn) notice('Hermes needs your input. Continue this session in full Hermes from Settings.', true);
      return;
    }
    const handler = state.pending.get(frame?.id);
    if (!handler) return;
    state.pending.delete(frame.id);
    if (frame.error) handler.reject(new RpcError(frame.error.message || 'Hermes refused the request.'));
    else handler.resolve(frame.result);
  });
  socket.addEventListener('close', () => {
    state.open = false;
    if (link === state) link = null;
    for (const call of state.pending.values()) call.reject(new Error('Hermes connection closed.'));
    state.pending.clear();
    if (turn?.admission) finish(turn, 'Connection lost. Reopen the session to check the message; it was not resent.', true);
  });
  state.ready = new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { socket.close(); reject(new Error('Hermes connection timed out.')); }, 25000);
    socket.addEventListener('open', () => {
      clearTimeout(timeout);
      if (socket.protocol === 'hermes-gateway-v1') { state.open = true; idleLink(); resolve(state); }
      else reject(new Error('This Hermes version does not support Fast.'));
    }, { once: true });
    socket.addEventListener('close', () => {
      clearTimeout(timeout); reject(new Error('Could not connect to Hermes.'));
    }, { once: true });
  });
  state.rpc = (method, params) => {
    if (socket.readyState !== WebSocket.OPEN) return Promise.reject(new Error('Hermes is reconnecting.'));
    const id = uid();
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        state.pending.delete(id); reject(new Error('Hermes did not acknowledge the request.'));
      }, 45000);
      const settle = fn => value => { clearTimeout(timeout); state.pending.delete(id); fn(value); };
      state.pending.set(id, { resolve: settle(resolve), reject: settle(reject) });
      socket.send(JSON.stringify({ jsonrpc: '2.0', id, method, params }));
    });
  };
  return state.ready;
}

function finish(current, label = '', error = false) {
  if (turn !== current) return;
  turn = null;
  clearTimeout(current.paint);
  current.output?.parentNode?.classList.remove('streaming');
  if (current.output && current.source) renderReply(current.output, current.source);
  else current.output?.parentNode.remove();
  if (authorized) notice(label || current.warn || '', error);
  controls();
  idleLink();
  void listSessions(true);
}


function event(current, frame) {
  if (turn !== current || !frame || !current.admission || frame.session_id !== current.id) return;
  const p = frame.payload || {};
  if (frame.type === 'session.replay_gap') {
    finish(current, 'The live stream was interrupted. Reopen the session to see saved messages.', true);
    return;
  }
  if ((frame.admission_id || p.admission_id) !== current.admission) return;
  const tail = atBottom();
  if (frame.type === 'message.delta' && typeof p.text === 'string') {
    if (!current.output) {
      const reply = message('assistant', '');
      reply.classList.add('streaming');
      ui.messages.append(reply);
      current.output = reply.lastElementChild;
    }
    current.source = (current.source || '') + p.text;
    if (!current.paint) current.paint = setTimeout(() => {
      current.paint = 0;
      const follow = atBottom();
      renderReply(current.output, current.source);
      if (follow) bottom();
    }, 70);
    notice();
  } else if (frame.type === 'message.complete') {
    const final = text(p.content) || text(p.text);
    if (current.output && final) current.source = final;
    else if (final) ui.messages.append(message('assistant', final));
    finish(current, p.status === 'interrupted' ? 'Response stopped.'
      : p.status === 'error' ? 'Hermes could not finish the response.' : '', p.status === 'error');
    if (current.voice && final && !['interrupted','error'].includes(p.status)) void speakReply(final);
  } else if (typeof frame.type === 'string' && frame.type.endsWith('.request')) {
    notice('Hermes needs your input. Continue this session in full Hermes from Settings.', true);
  }
  if (tail) bottom(); else syncLatest();
}

async function send() {
  const input = ui.prompt.value.trim();
  if ((!input && !attachments.length) || turn || reading || writing || audioBusy || recording || !authorized) return;
  const current = { frames: [], sent: false, voice: voiceMode };
  turn = current;
  controls();
  // Only announce the connect when it is genuinely cold; a warm socket makes
  // this flash pointless noise on every message.
  const slow = setTimeout(() => {
    if (turn === current && !link?.open) notice('Connecting to Hermes…');
  }, 250);
  try {
    await ensureLink();
    const rpc = current.rpc = (method, params) => ensureLink().then(state => state.rpc(method, params));
    let snapshot;
    if (selection) {
      snapshot = await rpc('session.resume', { session_id: selection.id, omit_messages: true });
      if (snapshot.running || snapshot.pending?.length || snapshot.prompts?.length || snapshot.open_requests?.length) {
        throw new Error('This conversation has active work. Wait or open it in full Hermes.');
      }
      if (modelChoice || effortChoice !== undefined) {
        // A refused pick must not cost the user their message: keep the
        // session's own model, say so once, and still send.
        try {
          if (modelChoice) {
            await rpc('session.mutate', { session_id: snapshot.session_id, request_id: uid(),
              operation: 'model', expected_revision: snapshot.revision,
              ...(Number.isSafeInteger(snapshot.execution_generation)
                && { expected_generation: snapshot.execution_generation }),
              payload: { model: modelChoice.model, provider: modelChoice.provider,
                ...(effortChoice ? { reasoning: effortChoice } : {}) } });
          } else {
            await rpc('session.mutate', { session_id: snapshot.session_id, request_id: uid(),
              operation: 'reasoning', expected_revision: snapshot.revision,
              payload: { effort: effortChoice } });
          }
        } catch (error) {
          current.warn = 'Hermes kept this session’s model: ' + (error.message || 'the change was refused.');
          modelChoice = null;
          effortChoice = undefined;
        }
      }
    } else {
      // `session.create` takes `reasoning` (CREATE_FIELDS), never
      // `reasoning_effort`: checking the latter rejected every gateway. An
      // unsupported option is dropped rather than blocking the conversation.
      const create = (await rpc('runtime.describe', {}))?.session_create || {};
      const allowed = new Set(Array.isArray(create.parameters) ? create.parameters : []);
      if (!(create.sources || []).includes('gui')) {
        throw new Error('This Hermes does not let Fast start sessions. Open one in full Hermes first.');
      }
      const request = { source: 'gui', request_id: uid(),
        title: (input || attachments[0]?.file.name || 'New chat').slice(0, 72) };
      const dropped = [];
      if (modelChoice) {
        if (['model', 'provider'].every(name => allowed.has(name))) Object.assign(request, modelChoice);
        else dropped.push('model');
      }
      if (effortChoice) {
        if (allowed.has('reasoning')) request.reasoning = effortChoice;
        else dropped.push('reasoning');
      }
      if (dropped.length) {
        current.warn = `This Hermes ignores ${dropped.join(' and ')} for new chats; the profile default is used.`;
        modelChoice = null;
        effortChoice = undefined;
      }
      snapshot = await rpc('session.create', request);
    }
    if (typeof snapshot.session_id !== 'string' || !snapshot.session_id) throw new Error('Hermes did not return a session.');
    current.id = snapshot.session_id;
    selection = { ...selection, id: current.id, title: selection?.title || snapshot.info?.title || (input || attachments[0]?.file.name).slice(0,72),
      model: modelChoice?.model || snapshot.info?.model || selection?.model,
      provider: modelChoice?.provider || snapshot.info?.provider || selection?.provider,
      reasoning_effort: effortChoice !== undefined ? effortChoice : snapshot.info?.reasoning_effort || selection?.reasoning_effort };
    modelChoice = null;
    effortChoice = undefined;
    $('title').textContent = titleFor(selection);
    updateModelLabel();
    updateEffort();
    const {refs,images} = await attachForTurn(rpc, current.id);
    if (!authorized) throw new Error('Sign-in required.');
    const payload = [refs.join('\n'),input].filter(Boolean).join('\n\n') || 'What do you see in this image?';
    $('welcome').hidden = true;
    current.user = message('user', [attachments.map(a=>a.file.name).join(' · '),input].filter(Boolean).join('\n'));
    ui.messages.append(current.user);
    bottom();
    current.sent = true;
    // Never replay a submit automatically, even when the transport loses its receipt.
    current.draft = ui.prompt.value;
    ui.prompt.value = '';
    fitInput();
    notice('Waiting for Hermes…');
    const receipt = await rpc('prompt.submit', { session_id: current.id, input_id: uid(), text: payload,
      ...(images.length && {attachments:images}),
      ...(current.voice && {voice_turn:true}) });
    attachments = []; drawAttachments();
    if (receipt.voice_stopped === true) {
      current.user.remove();
      finish(current, 'Voice mode stopped; no message was sent.');
      return;
    }
    if (!receipt.admission_id || receipt.ref?.session_id !== current.id) throw new Error('Hermes did not confirm the message.');
    current.admission = receipt.admission_id;
    if (receipt.status === 'queued') notice('Message queued in Hermes.');
    controls();
    for (const frame of current.frames) event(current, frame);
    current.frames.length = 0;
  } catch (error) {
    if (!current.sent || error instanceof RpcError) {
      current.user?.remove();
      if (current.draft && !ui.prompt.value) ui.prompt.value = current.draft;
      fitInput();
      finish(current, error.message || 'Could not send the message.', true);
    } else {
      finish(current, 'Delivery was not confirmed. Check the session before resending.', true);
    }
  } finally {
    clearTimeout(slow);
  }
}

async function stop() {
  const current = turn;
  if (!current?.admission || current.stopping) return;
  current.stopping = true;
  controls();
  try {
    await current.rpc('prompt.cancel', { session_id: current.id, admission_id: current.admission });
    if (turn === current) finish(current, 'Stop requested. Reopen the session to see its final state.');
  } catch {
    if (turn === current) {
      notice('Could not confirm the stop. Check full Hermes before retrying.', true);
      current.stopping = false;
      controls();
    }
  }
}

function modelName(id) {
  const name = id.split('/').pop().replace(/-\d{8}$/, '');
  if (/^gpt-/i.test(name)) return name.replace(/^gpt/i,'GPT');
  return name.replace(/^claude-/,'').replace(/(\d)-(?=\d)/g,'$1.')
    .replace(/-/g,' ').replace(/\b[a-z]/g, c => c.toUpperCase());
}

function updateModelLabel() {
  const id = modelChoice?.model || selection?.model || defaultModel?.model;
  ui.model.textContent = id ? modelName(id) : 'Default model';
  ui.model.title = id || 'Choose a model';
  ui.model.setAttribute('aria-label', id ? `Choose a model: ${modelName(id)}` : 'Choose a model');
}

function popup(panel, anchor) {
  if (panel.matches(':popover-open')) return;
  panel.showPopover();
  const place = () => {
    if (!panel.matches(':popover-open')) return;
    const vv = window.visualViewport;
    const left = vv?.offsetLeft || 0, top = vv?.offsetTop || 0;
    const width = vv?.width || innerWidth, height = vv?.height || innerHeight;
    panel.style.maxHeight = `min(65dvh,${Math.max(48,height - 12)}px)`;
    const r = anchor.getBoundingClientRect(), box = panel.getBoundingClientRect();
    panel.style.left = Math.max(left+6, Math.min(left+width-box.width-6, r.right-box.width)) + 'px';
    panel.style.top = Math.max(top+6, Math.min(top+height-box.height-6,
      r.top-top >= box.height+6 ? r.top-box.height-4 : r.bottom+4)) + 'px';
    // Grow out of the control that opened it, on the side it actually landed.
    const above = panel.getBoundingClientRect().bottom <= r.top + 4;
    const centre = Math.max(8, Math.min(box.width - 8, r.left + r.width/2 - panel.getBoundingClientRect().left));
    panel.style.setProperty('--origin',
      `${above ? 'bottom' : 'top'} ${Math.round(centre)}px`);
  };
  place();
  const observer = new ResizeObserver(place);
  observer.observe(panel); observer.observe(anchor);
  window.addEventListener('resize',place);
  window.visualViewport?.addEventListener('resize',place);
  window.visualViewport?.addEventListener('scroll',place);
  panel.addEventListener('toggle', function closed() {
    if (panel.matches(':popover-open')) return;
    observer.disconnect(); window.removeEventListener('resize',place);
    window.visualViewport?.removeEventListener('resize',place);
    window.visualViewport?.removeEventListener('scroll',place);
    panel.removeEventListener('toggle',closed);
  });
}

function editSession(remove,row = selection) {
  if (!row || turn || writing) return;
  editRow = row;
  deleting = remove;
  $('session-heading').textContent = remove ? 'Delete session?' : 'Rename session';
  $('session-name').disabled = $('session-name').hidden = remove;
  $('session-name').value = titleFor(editRow);
  $('delete-question').textContent = remove ? `Delete “${titleFor(editRow)}”? This cannot be undone.` : '';
  $('save-edit').textContent = remove ? 'Delete' : 'Save';
  $('save-edit').classList.toggle('danger',remove);
  $('session-error').textContent = '';
  $('session-dialog').showModal();
  if (remove) $('cancel-edit').focus(); else $('session-name').select();
}

async function saveSession(e) {
  e.preventDefault();
  const row = editRow, remove = deleting, title = $('session-name').value.trim();
  if (!row || writing || turn || !authorized || (!remove && !title)) return;
  writing = true;
  $('save-edit').disabled = $('cancel-edit').disabled = true;
  $('session-error').textContent = '';
  const path = '/api/sessions/'+encodeURIComponent(row.id);
  // Retain the same identity after an ambiguous transport failure.
  const intent = JSON.stringify([row.id,remove,remove ? null : title]);
  try {
    if (!mutations.has(intent)) {
      const s = await api(scoped(path+'/mutation-snapshot'));
      if (!s.exists || s.session_id !== row.id || ![s.runtime_revision,s.runtime_generation]
        .every(v => Number.isSafeInteger(v) && v >= 0)) throw new Error('Session changed. Refresh the list.');
      mutations.set(intent,{request_id:uid(), expected_revision:s.runtime_revision, expected_generation:s.runtime_generation});
    }
    const identity = mutations.get(intent);
    const result = remove ? await api(scoped(path,identity),'DELETE')
      : await api(scoped(path),'PATCH',{title,...identity,...(profile && {profile})});
    if (result.ok !== true) throw new Error('Hermes did not confirm the change.');
    for (const key of mutations.keys()) if (JSON.parse(key)[0] === row.id) mutations.delete(key);
    $('session-dialog').close();
    if (remove) {
      rows = rows.filter(r => r.id !== row.id);
      if (selection?.id === row.id) select(null);
      loaded = Math.max(0,loaded-1); total = Math.max(0,total-1);
    } else {
      for (const r of [selection,...rows]) if (r?.id === row.id) r.title = result.title || title;
      if (selection?.id === row.id) $('title').textContent = titleFor(selection);
    }
    drawSessions();
    if (remove) await listSessions(true);
  } catch (err) {
    if (err.status >= 400 && err.status < 500) mutations.delete(intent);
    $('session-error').textContent = err.status === 409 ? 'Session changed or is busy. Check it before retrying.' : err.message;
  } finally {
    writing = false;
    $('save-edit').disabled = $('cancel-edit').disabled = false;
    controls();
  }
}

function drawModels() {
  const query = $('model-filter').value.trim().toLowerCase();
  const list = $('model-list');
  list.replaceChildren();
  if (!models) return;
  const current = modelChoice || (selection?.model ? selection : defaultModel);
  for (const provider of models) {
    const matches = provider.models.filter(id => (id+' '+modelName(id)+' '+provider.name).toLowerCase().includes(query));
    if (!matches.length) continue;
    const group = node('details'), label = node('summary',provider.name);
    group.open = true; group.append(label);
    let shown = 0;
    const more = node('button','Show more','quiet');
    more.type = 'button';
    function page() {
      for (const id of matches.slice(shown,shown+50)) {
        const b = node('button', modelName(id), 'setting-row');
        b.type = 'button'; b.title = id;
        if (current?.model === id && (!current.provider || current.provider === provider.slug)) b.setAttribute('aria-current','true');
        b.addEventListener('click', () => {
          modelChoice = {model:id,provider:provider.slug}; updateModelLabel();
          $('model-dialog').hidePopover(); ui.model.focus();
        });
        group.append(b);
      }
      shown += 50;
      if (shown < matches.length) group.append(more); else more.remove();
    }
    more.addEventListener('click',page);
    page(); list.append(group);
  }
  $('model-status').textContent = list.childElementCount ? '' : 'No matching models.';
}

async function openModels() {
  $('model-filter').value = '';
  popup($('model-dialog'),ui.model);
  if (matchMedia('(pointer: fine)').matches) $('model-filter').focus();
  if (models) return drawModels();
  if (fetchingModels) return;
  fetchingModels = true;
  $('model-status').textContent = 'Loading models…';
  try {
    const data = await api(scoped('/api/model/options'));
    models = data.providers.map(row => ({slug:row.slug,name:row.name || row.slug,
      models:(row.models || []).filter(m => typeof m === 'string')}));
    defaultModel = {model:data.model,provider:data.provider}; updateModelLabel();
    drawModels();
  } catch {
    $('model-status').textContent = 'Models unavailable. Close and reopen to retry.';
  } finally {
    fetchingModels = false;
  }
}

composer.addEventListener('submit', e => { e.preventDefault(); void send(); });
function fitInput() {
  if (!ui.prompt.value) delete composer.dataset.expanded;
  ui.prompt.style.height = 'auto';
  if (ui.prompt.value && (ui.prompt.value.trimEnd().includes('\n') || ui.prompt.scrollHeight > 32)) composer.dataset.expanded = 'true';
  ui.prompt.style.height = `${Math.max(26,ui.prompt.scrollHeight)}px`;
}
ui.prompt.addEventListener('input', () => { fitInput(); controls(); });
window.addEventListener('resize',fitInput);
ui.prompt.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && matchMedia('(pointer: fine)').matches) {
    e.preventDefault();
    void send();
  }
});
ui.stop.addEventListener('click', stop);
ui.model.addEventListener('click', openModels);
$('model-filter').addEventListener('input', drawModels);
$('model-dialog').addEventListener('keydown',e => {
  if (!['ArrowDown','ArrowUp','Enter'].includes(e.key) || e.isComposing) return;
  const items = [...$('model-list').querySelectorAll('summary,button')].filter(b => b.getClientRects().length);
  if (!items.length || (e.key === 'Enter' && e.target !== $('model-filter'))) return;
  e.preventDefault();
  if (e.key === 'Enter') { items.find(b => b.classList.contains('setting-row'))?.click(); return; }
  const i = items.indexOf(document.activeElement);
  items[(i+(e.key === 'ArrowDown'?1:-1)+items.length)%items.length].focus();
});
$('rename-active').addEventListener('click',()=>editSession(false));
$('title').addEventListener('dblclick',()=>editSession(false));
$('cancel-edit').addEventListener('click',()=>$('session-dialog').close());
$('session-dialog').addEventListener('cancel',e=>{ if (writing) e.preventDefault(); });
$('session-form').addEventListener('submit',saveSession);
$('new').addEventListener('click', () => select(null));
$('older').addEventListener('click', () => { if (!turn) void loadHistory(true); });
$('more').addEventListener('click', () => listSessions());
$('refresh').addEventListener('click', () => listSessions(true));
$('open-sessions').addEventListener('click', () => sessionsOpen(true));
$('close-sessions').addEventListener('click', () => sessionsOpen(false));
for (const id of ['settings', 'mobile-settings']) $(id).addEventListener('click', () => $('settings-dialog').showModal());
$('signout').addEventListener('submit', () => { try { sessionStorage.removeItem(key); } catch {} });
$('appearance').value = appearance;
$('appearance').addEventListener('change', () => {
  appearance = $('appearance').value;
  try { localStorage.setItem(APPEARANCE,appearance); } catch {}
  paintTheme();
});

try { token = sessionStorage.getItem(key); } catch {}
bindComposer();
// A hidden tab keeps its socket for the warm path; leaving the page never should.
window.addEventListener('pagehide', closeLink);
// The jump pill floats exactly above the dock, whatever it measures.
new ResizeObserver(([entry]) => document.querySelector('.chat')
  .style.setProperty('--dock-h', entry.target.offsetHeight + 'px'))
  .observe(document.querySelector('.composer-area'));
let latestTick = 0;
ui.history.addEventListener('scroll', () => {
  if (latestTick) return;
  latestTick = requestAnimationFrame(() => { latestTick = 0; syncLatest(); });
}, { passive: true });
$('latest').addEventListener('click', () => {
  const smooth = !matchMedia('(prefers-reduced-motion: reduce)').matches;
  ui.history.scrollTo({ top: ui.history.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
});
syncLatest();
controls();
if (!/^[A-Za-z0-9_-]{43}$/.test(token || '')) {
  notice('Connecting securely to Hermes…');
  $('reconnect').hidden = false;
  location.replace(signIn);
} else {
  paintTheme();
  systemDark.addEventListener('change',paintTheme);
  const syncTheme = () => api('/api/ui-preferences')
    .then(data => { themePrefs = data.values || {}; paintTheme(); }).catch(() => {});
  void syncTheme();
  document.addEventListener('visibilitychange',() => { if (!document.hidden && authorized) void syncTheme(); });
  void listSessions(true);
}
