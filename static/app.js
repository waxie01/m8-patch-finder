'use strict';

// ─── State ────────────────────────────────────────────────────────────────────
// IDLE → LOADING → LOADED → ANALYZING (can return to LOADED after analyze)
let STATE      = 'IDLE';
let loadId     = null;
let analyzeId  = null;
let ws         = null;   // WaveSurfer instance
let cropStart  = null;
let cropEnd    = null;

// ─── DOM ──────────────────────────────────────────────────────────────────────
const urlInput      = document.getElementById('url-input');
const loadBtn       = document.getElementById('load-btn');
const loadProgress  = document.getElementById('load-progress');
const loadError     = document.getElementById('load-error');

const waveSection   = document.getElementById('wave-section');
const trackInfo     = document.getElementById('track-info');
const playBtn       = document.getElementById('play-btn');
const timeCurrent   = document.getElementById('time-current');
const timeTotal     = document.getElementById('time-total');
const cropStartEl   = document.getElementById('crop-start');
const cropEndEl     = document.getElementById('crop-end');
const descInput     = document.getElementById('desc-input');
const stemSelect    = document.getElementById('stem-select');
const analyzeBtn    = document.getElementById('analyze-btn');

const resultsSection  = document.getElementById('results-section');
const analyzeError    = document.getElementById('analyze-error');
const resultsContent  = document.getElementById('results-content');
const spectrogramImg  = document.getElementById('spectrogram-img');
const resultJson      = document.getElementById('result-json');
const copyBtn         = document.getElementById('copy-btn');
const reAnalyzeBtn    = document.getElementById('re-analyze-btn');

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtTime(sec) {
  if (sec == null || isNaN(sec)) return '--:--';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function show(el)   { el.classList.remove('hidden'); }
function hide(el)   { el.classList.add('hidden'); }
function showId(id) { document.getElementById(id).classList.remove('hidden'); }
function hideId(id) { document.getElementById(id).classList.add('hidden'); }

function setRow(rowId, barId, pctId, state, pct) {
  const row  = document.getElementById(rowId);
  const bar  = document.getElementById(barId);
  const pctEl = document.getElementById(pctId);
  row.classList.remove('active', 'done');
  if (state === 'active') row.classList.add('active');
  if (state === 'done')   row.classList.add('done');
  if (pct !== null && pct !== undefined) {
    bar.style.width      = pct + '%';
    pctEl.textContent    = pct + '%';
  }
}

function resetRow(rowId, barId, pctId) {
  setRow(rowId, barId, pctId, '', 0);
  document.getElementById(pctId).textContent = '---';
}

function showError(container, msg) {
  container.textContent = '> ERROR: ' + msg;
  show(container);
}

function clearError(container) {
  hide(container);
  container.textContent = '';
}

// ─── Section 01: Load ─────────────────────────────────────────────────────────

loadBtn.addEventListener('click', handleLoad);
urlInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') handleLoad();
});

async function handleLoad() {
  const url = urlInput.value.trim();
  if (!url || STATE === 'LOADING') return;

  STATE = 'LOADING';
  loadBtn.disabled = true;
  clearError(loadError);
  show(loadProgress);
  resetRow('row-download', 'bar-download', 'pct-download');
  setRow('row-download', 'bar-download', 'pct-download', 'active', 0);

  try {
    const res  = await fetch('/api/load', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ url }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    loadId = data.job_id;

    if (data.status === 'done') {
      // Disk-cached: skip SSE
      setRow('row-download', 'bar-download', 'pct-download', 'done', 100);
      await initWaveSection(data.audio_url, url);
      return;
    }

    // Stream download progress via SSE
    const evtSrc = new EventSource(`/api/load/${loadId}/stream`);

    evtSrc.onmessage = async (e) => {
      const ev = JSON.parse(e.data);

      if (ev.status === 'already_done') {
        evtSrc.close();
        setRow('row-download', 'bar-download', 'pct-download', 'done', 100);
        await initWaveSection(`/api/audio/${loadId}`, url);
        return;
      }

      if (ev.status === 'done') {
        evtSrc.close();
        setRow('row-download', 'bar-download', 'pct-download', 'done', 100);
        await initWaveSection(ev.audio_url, url);
        return;
      }

      if (ev.status === 'error') {
        evtSrc.close();
        showError(loadError, ev.message);
        STATE = 'IDLE';
        loadBtn.disabled = false;
        return;
      }

      if (ev.stage === 'download') {
        setRow('row-download', 'bar-download', 'pct-download', 'active', ev.progress);
      }
    };

    evtSrc.onerror = () => {
      evtSrc.close();
      showError(loadError, 'Connection error. Refresh and try again.');
      STATE = 'IDLE';
      loadBtn.disabled = false;
    };

  } catch (err) {
    showError(loadError, err.message);
    STATE = 'IDLE';
    loadBtn.disabled = false;
  }
}

// ─── Section 02: Waveform + Configure ────────────────────────────────────────

async function initWaveSection(audioUrl, originalUrl) {
  STATE = 'LOADED';
  loadBtn.disabled = false;

  // Show section
  show(waveSection);
  setTimeout(() => waveSection.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80);

  // Track label
  const slug = decodeURIComponent(
    (originalUrl || '').replace(/[?&].*/, '').split('/').filter(Boolean).pop() || 'track'
  ).slice(0, 80);
  trackInfo.textContent = `SOURCE  ${slug}`;

  // Destroy old WaveSurfer
  if (ws) { ws.destroy(); ws = null; }
  cropStart = null;
  cropEnd   = null;
  cropStartEl.textContent = '--:--';
  cropEndEl.textContent   = '--:--';
  playBtn.disabled = true;
  playBtn.textContent = '▶ PLAY';

  // Build WaveSurfer
  const RegionsPlugin = WaveSurfer.RegionsPlugin.create();

  ws = WaveSurfer.create({
    container:     '#waveform',
    url:           audioUrl,
    waveColor:     '#1a8a30',
    progressColor: '#ffb000',
    cursorColor:   '#ffb000',
    cursorWidth:   1,
    height:        82,
    normalize:     true,
    interact:      true,
    plugins:       [RegionsPlugin],
  });

  // Drag-select creates a region; only one at a time
  RegionsPlugin.enableDragSelection({ color: 'rgba(255, 176, 0, 0.10)' });

  RegionsPlugin.on('region-created', (region) => {
    RegionsPlugin.getRegions().forEach((r) => {
      if (r.id !== region.id) r.remove();
    });
    cropStart = region.start;
    cropEnd   = region.end;
    updateCropDisplay();
  });

  RegionsPlugin.on('region-updated', (region) => {
    cropStart = region.start;
    cropEnd   = region.end;
    updateCropDisplay();
  });

  ws.on('timeupdate', (t)        => { timeCurrent.textContent = fmtTime(t); });
  ws.on('ready',      (duration) => {
    playBtn.disabled  = false;
    timeTotal.textContent = fmtTime(duration);
  });
  ws.on('play',   () => { playBtn.textContent = '⏸ PAUSE'; });
  ws.on('pause',  () => { playBtn.textContent = '▶ PLAY'; });
  ws.on('finish', () => { playBtn.textContent = '▶ PLAY'; });
}

function updateCropDisplay() {
  cropStartEl.textContent = fmtTime(cropStart);
  cropEndEl.textContent   = fmtTime(cropEnd);
}

playBtn.addEventListener('click', () => ws?.playPause());

// ─── Section 03: Analyze ──────────────────────────────────────────────────────

analyzeBtn.addEventListener('click', handleAnalyze);

async function handleAnalyze() {
  if (STATE !== 'LOADED' || !loadId) return;

  const description = descInput.value.trim();
  if (!description) {
    descInput.focus();
    const orig = descInput.style.borderColor;
    descInput.style.borderColor = 'var(--error)';
    descInput.style.boxShadow   = '0 0 8px rgba(255,60,60,0.3)';
    setTimeout(() => {
      descInput.style.borderColor = orig;
      descInput.style.boxShadow   = '';
    }, 1600);
    return;
  }

  STATE = 'ANALYZING';
  analyzeBtn.disabled = true;
  clearError(analyzeError);
  hide(resultsContent);

  // Reset progress rows
  ['stems', 'analyze', 'spectrogram'].forEach((step) => {
    resetRow(`row-${step}`, `bar-${step}`, `pct-${step}`);
  });

  show(resultsSection);
  setTimeout(() => resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80);

  const stem = stemSelect.value;

  try {
    const res = await fetch('/api/analyze', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        load_id:     loadId,
        description,
        stem,
        start_sec:   cropStart,
        end_sec:     cropEnd,
      }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    analyzeId = data.job_id;

    if (data.status === 'done') {
      // Cached result
      markAllStepsDone();
      await showResults();
      return;
    }

    // Stream analysis progress
    const evtSrc = new EventSource(`/api/analyze/${analyzeId}/stream`);

    evtSrc.onmessage = async (e) => {
      const ev = JSON.parse(e.data);

      if (ev.status === 'already_done') {
        evtSrc.close();
        markAllStepsDone();
        await showResults();
        return;
      }

      if (ev.status === 'done') {
        evtSrc.close();
        markAllStepsDone();
        spectrogramImg.src = ev.spectrogram_url + '?t=' + Date.now();
        await showResults();
        return;
      }

      if (ev.status === 'error') {
        evtSrc.close();
        showError(analyzeError, ev.message);
        STATE = 'LOADED';
        analyzeBtn.disabled = false;
        return;
      }

      // Progress event — mark prior steps done, current active
      const steps = ['stems', 'analyze', 'spectrogram'];
      const idx   = steps.indexOf(ev.stage);
      if (idx >= 0) {
        steps.slice(0, idx).forEach((s) => {
          setRow(`row-${s}`, `bar-${s}`, `pct-${s}`, 'done', 100);
        });
        setRow(`row-${ev.stage}`, `bar-${ev.stage}`, `pct-${ev.stage}`,
               'active', ev.progress);
      }
    };

    evtSrc.onerror = () => {
      evtSrc.close();
      showError(analyzeError, 'Connection lost during analysis.');
      STATE = 'LOADED';
      analyzeBtn.disabled = false;
    };

  } catch (err) {
    showError(analyzeError, err.message);
    STATE = 'LOADED';
    analyzeBtn.disabled = false;
  }
}

function markAllStepsDone() {
  ['stems', 'analyze', 'spectrogram'].forEach((s) => {
    setRow(`row-${s}`, `bar-${s}`, `pct-${s}`, 'done', 100);
  });
}

async function showResults() {
  try {
    const res  = await fetch(`/api/result/${analyzeId}`);
    const data = await res.json();

    resultJson.textContent = JSON.stringify(data, null, 2);
    spectrogramImg.src     = `/api/spectrogram/${analyzeId}?t=${Date.now()}`;

    show(resultsContent);
    STATE = 'LOADED';
    analyzeBtn.disabled = false;

    setTimeout(() => resultsContent.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80);
  } catch (err) {
    showError(analyzeError, 'Failed to load results: ' + err.message);
    STATE = 'LOADED';
    analyzeBtn.disabled = false;
  }
}

// ─── Copy + Back ──────────────────────────────────────────────────────────────

copyBtn.addEventListener('click', () => {
  const text = resultJson.textContent;
  if (!text) return;
  navigator.clipboard.writeText(text).then(() => {
    const orig = copyBtn.textContent;
    copyBtn.textContent        = 'COPIED!';
    copyBtn.style.borderColor  = 'var(--green)';
    copyBtn.style.color        = 'var(--green)';
    setTimeout(() => {
      copyBtn.textContent       = orig;
      copyBtn.style.borderColor = '';
      copyBtn.style.color       = '';
    }, 2000);
  }).catch(() => {
    // Fallback: select text
    const sel = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(resultJson);
    sel.removeAllRanges();
    sel.addRange(range);
  });
});

reAnalyzeBtn.addEventListener('click', () => {
  hide(resultsSection);
  hide(resultsContent);
  STATE = 'LOADED';
  analyzeBtn.disabled = false;
  setTimeout(() => waveSection.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80);
});
