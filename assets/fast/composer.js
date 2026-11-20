'use strict';

let attachments = [], effortChoice, recording, audioBusy = false, voiceMode = false, voiceEpoch = 0;
const canRecord = !!(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
const efforts = [null,'minimal','low','medium','high','xhigh','max','ultra'];
const effortName = value => ({xhigh:'Extra high',none:'Off'})[value] ||
  (value ? value[0].toUpperCase()+value.slice(1) : 'Effort');

function updateEffort() {
  const label = effortName(effortChoice === undefined ? selection?.reasoning_effort : effortChoice);
  $('effort').textContent = label;
  $('effort').setAttribute('aria-label', 'Reasoning effort: '+label);
}

function drawAttachments() {
  const list = $('attachments');
  list.hidden = !attachments.length;
  list.replaceChildren(...attachments.map(item => {
    const b = node('button', item.file.name+' ×', 'attachment');
    b.type = 'button'; b.title = item.file.name;
    b.setAttribute('aria-label','Remove '+item.file.name);
    b.addEventListener('click', () => {
      attachments = attachments.filter(a => a !== item);
      drawAttachments(); controls();
    });
    return b;
  }));
}

function addFiles(files) {
  if (!authorized || turn || !files.length) return;
  let omitted = false;
  for (const file of files) {
    const image = /^image\/(png|jpeg|webp|gif)$/.test(file.type);
    if (!file.size || file.size > (image ? 4 : 16)*1024*1024 || attachments.length === 6) {
      omitted = true; continue;
    }
    attachments.push({file,image});
  }
  drawAttachments(); controls();
  notice(omitted ? 'Up to 6 non-empty files: 4 MiB per image, 16 MiB per other file.' : '',omitted);
}

function dataUrl(blob) {
  return new Promise((resolve,reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('Could not read the file.'));
    reader.readAsDataURL(blob);
  });
}

async function attachForTurn(rpc,id) {
  const refs = [], images = [];
  for (const a of attachments) {
    if (a.session !== id) {
      let result;
      if (a.image) {
        const base64 = (await dataUrl(a.file)).split(',')[1];
        result = await rpc('image.attach_bytes',{session_id:id,content_base64:base64,filename:a.file.name});
      } else {
        if (!a.staged) {
          const form = new FormData(); form.append('file',a.file);
          const staged = await api(scoped('/api/chat/file-upload'),'POST',form,120000);
          if (!staged.ok || !staged.staged_upload) throw new Error('Hermes did not stage '+a.file.name);
          a.staged = staged.staged_upload;
        }
        result = await rpc('file.attach',{session_id:id,name:a.file.name,staged_upload:a.staged});
      }
      if (!result.attached || (a.image ? !(result.path && result.mime) : typeof result.ref_text !== 'string')) {
        throw new Error('Could not attach '+a.file.name);
      }
      a.session = id;
      if (a.image) a.media = {path:result.path,mime:result.mime};
      else a.ref = result.ref_text;
    }
    if (a.ref) refs.push(a.ref);
    if (a.media) images.push(a.media);
  }
  return {refs,images};
}

function clearComposerMedia() {
  ++voiceEpoch;
  if (recording) recording.stop();
  voiceMode = false;
  attachments = [];
  drawAttachments();
  const player = $('voice-player');
  player.pause(); player.removeAttribute('src'); player.load(); player.hidden = true;
  $('voice').setAttribute('aria-pressed','false');
}

async function capture(button) {
  if (recording) { if (recording.button === button) recording.stop(); return; }
  if (!canRecord || audioBusy || turn || !authorized) return;
  const voice = button.id === 'voice', epoch = voiceEpoch;
  let stream;
  audioBusy = true; controls();
  try {
    stream = await navigator.mediaDevices.getUserMedia({audio:true});
    if (epoch !== voiceEpoch || !authorized) { stream.getTracks().forEach(t=>t.stop()); return; }
    const rec = new MediaRecorder(stream), chunks = [];
    let size = 0, timedOut = false;
    const stop = (limit = false) => {
      timedOut ||= limit;
      if (rec.state !== 'inactive') rec.stop();
      stream.getTracks().forEach(t=>t.stop());
      clearTimeout(timer);
    };
    rec.ondataavailable = e => {
      chunks.push(e.data); size += e.data.size;
      if (size > 8*1024*1024) stop(true);
    };
    rec.onstop = async () => {
      recording = null;
      button.setAttribute('aria-pressed','false');
      if (epoch !== voiceEpoch || !authorized) { controls(); return; }
      if (timedOut) { notice('Recording limit reached. Try a shorter recording.',true); controls(); return; }
      audioBusy = true; controls();
      let submit = false;
      try {
        const audio = new Blob(chunks,{type:rec.mimeType || chunks[0]?.type || 'audio/webm'});
        if (!audio.size || audio.size > 9*1024*1024) throw new Error('Recording empty or too long.');
        notice('Transcribing…');
        const encoded = await dataUrl(audio);
        if (epoch !== voiceEpoch || !authorized) return;
        const result = await api(scoped('/api/audio/transcribe'),'POST',
          {data_url:encoded,mime_type:audio.type},120000);
        if (epoch !== voiceEpoch || !authorized) return;
        const words = typeof result.transcript === 'string' ? result.transcript.trim() : '';
        if (!words) { notice('No speech detected.'); return; }
        const combined = [ui.prompt.value.trim(),words].filter(Boolean).join(' ');
        ui.prompt.value = combined.slice(0, ui.prompt.maxLength);
        fitInput();
        voiceMode = voice;
        submit = voice;
        notice(voice ? '' : 'Review the transcription before sending.');
      } catch (error) { if (epoch === voiceEpoch) notice(error.message || 'Transcription unavailable.',true); }
      finally { audioBusy = false; controls(); }
      if (submit) void send();
    };
    rec.onerror = () => stop();
    rec.start(1000);
    const timer = setTimeout(()=>stop(true),90000);
    recording = {button,stop};
    voiceMode = false;
    button.setAttribute('aria-pressed','true');
    notice(voice ? 'Recording… Tap the waveform to send.' : 'Recording… Tap the microphone when done.');
  } catch {
    stream?.getTracks().forEach(t=>t.stop());
    if (epoch === voiceEpoch) notice('Microphone unavailable. Check browser permissions.',true);
  } finally { audioBusy = false; controls(); }
}

async function speakReply(text) {
  const epoch = voiceEpoch;
  voiceMode = false;
  try {
    const result = await api(scoped('/api/audio/speak'),'POST',{text:text.slice(0,10000)},120000);
    if (epoch !== voiceEpoch || !authorized || typeof result.data_url !== 'string') return;
    if (!/^data:audio\/[\w.+-]+;base64,[A-Za-z0-9+/=]+$/.test(result.data_url)) throw new Error();
    const player = $('voice-player');
    player.src = result.data_url; player.hidden = false;
    await player.play().catch(() => {});
  } catch { if (epoch === voiceEpoch) notice('Audio playback unavailable; the reply is shown above.',true); }
}

function bindComposer() {
  $('attach').addEventListener('click',()=>$('files').click());
  $('files').addEventListener('change',e=>{ addFiles(e.target.files); e.target.value=''; });
  ui.prompt.addEventListener('paste',e=>{
    if (e.clipboardData?.files.length && !e.clipboardData.getData('text/plain') && authorized && !turn) {
      e.preventDefault(); addFiles(e.clipboardData.files);
    }
  });
  composer.addEventListener('dragover',e=>{ if (e.dataTransfer.types.includes('Files')) e.preventDefault(); });
  composer.addEventListener('drop',e=>{ if (e.dataTransfer.files.length) { e.preventDefault(); addFiles(e.dataTransfer.files); } });
  $('effort').addEventListener('click',() => {
    const menu = $('effort-menu');
    menu.replaceChildren(...efforts.map(value => {
      const button = node('button', value ? effortName(value) : 'Profile default','setting-row');
      button.type = 'button';
      const current = effortChoice === undefined ? selection?.reasoning_effort ?? null : effortChoice;
      if (value === current) button.setAttribute('aria-current','true');
      button.addEventListener('click',()=>{ effortChoice = value; updateEffort(); menu.hidePopover(); $('effort').focus(); });
      return button;
    }));
    popup(menu,$('effort'));
    (menu.querySelector('[aria-current]') || menu.firstElementChild).focus();
  });
  for (const id of ['dictate','voice']) {
    const button = $(id);
    if (!canRecord) button.title = 'Microphone unavailable in this browser';
    button.addEventListener('click',()=>capture(button));
  }
  window.addEventListener('pagehide',()=>{ ++voiceEpoch; recording?.stop(); });
}
