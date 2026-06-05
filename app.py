#!/usr/bin/env python3
"""
M8 Patch Finder — Web GUI
Run:  python3 app.py
Then: http://localhost:5000
"""

import sys
import re
import json
import hashlib
import threading
import queue as qlib
import time
import subprocess
from pathlib import Path

from flask import (Flask, request, jsonify, Response,
                   send_file, render_template, stream_with_context)

# Import pure analysis functions from analyze.py (CLI still works independently)
sys.path.insert(0, str(Path(__file__).parent))
import analyze as pipeline

app = Flask(__name__)

OUTPUT_ROOT = Path('output')
WORKSPACE   = OUTPUT_ROOT / '_workspace'

# In-memory job store  { job_id: dict }
# All access protected by _jobs_lock
_jobs: dict = {}
_jobs_lock = threading.Lock()


# ─── Utilities ────────────────────────────────────────────────────────────────

def _job_id(*parts: str) -> str:
    return hashlib.md5('|'.join(parts).encode()).hexdigest()[:12]


def _new_job(job_id: str, job_type: str) -> dict:
    job = {
        'job_id':   job_id,
        'type':     job_type,
        'status':   'pending',
        'wav_path': None,
        'stems':    {},
        'spec_path': None,
        'result':   None,
        'error':    None,
        '_queue':   qlib.Queue(),
    }
    with _jobs_lock:
        _jobs[job_id] = job
    return job


def _push_event(job_id: str, event: dict):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return
    job['_queue'].put(event)
    status = event.get('status')
    if status in ('done', 'error'):
        with _jobs_lock:
            _jobs[job_id]['status'] = status
            if status == 'error':
                _jobs[job_id]['error'] = event.get('message', 'Unknown error')


def _sse_stream(job_id: str):
    """Generator: yields SSE text from a job's queue until done/error."""
    with _jobs_lock:
        job = _jobs.get(job_id)

    if not job:
        yield f'data: {json.dumps({"status":"error","message":"Job not found"})}\n\n'
        return

    # Already finished before SSE connected?
    with _jobs_lock:
        current = _jobs[job_id]['status']

    if current == 'done':
        yield f'data: {json.dumps({"status":"already_done"})}\n\n'
        return
    if current == 'error':
        msg = _jobs[job_id].get('error', 'Unknown error')
        yield f'data: {json.dumps({"status":"error","message":msg})}\n\n'
        return

    q = job['_queue']
    last_ping = time.time()

    while True:
        # Keep-alive comment prevents proxy/nginx 60 s timeout during Demucs
        if time.time() - last_ping > 15:
            yield ': ping\n\n'
            last_ping = time.time()

        try:
            event = q.get(timeout=1)
            yield f'data: {json.dumps(event)}\n\n'
            if event.get('status') in ('done', 'error'):
                break
        except qlib.Empty:
            # Fallback: job status changed without a queue event (shouldn't happen)
            with _jobs_lock:
                s = _jobs.get(job_id, {}).get('status')
            if s in ('done', 'error'):
                break


def _sse_response(generator):
    resp = Response(stream_with_context(generator), mimetype='text/event-stream')
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['X-Accel-Buffering'] = 'no'
    return resp


# ─── Stem cache helper ────────────────────────────────────────────────────────

def _stems_cached(wav_path: Path, stems_dir: Path):
    """Return {name: Path} for all 4 stems if they all exist, else None."""
    stems = {}
    for name in ('drums', 'bass', 'vocals', 'other'):
        p = stems_dir / 'htdemucs' / wav_path.stem / f'{name}.wav'
        if not p.exists():
            found = list(stems_dir.glob(f'**/{name}.wav'))
            if found:
                p = found[0]
            else:
                return None
        stems[name] = p
    return stems


# ─── Worker: download ─────────────────────────────────────────────────────────

def _load_worker(load_id: str, url: str):
    dl_dir = WORKSPACE / 'downloads' / load_id
    dl_dir.mkdir(parents=True, exist_ok=True)
    try:
        cmd = [
            'python3', '-m', 'yt_dlp',
            '-x', '--audio-format', 'wav', '--audio-quality', '0',
            '--no-playlist', '--newline',
            '-o', str(dl_dir / '%(title)s.%(ext)s'),
            url,
        ]
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        for line in proc.stdout:
            m = re.search(r'(\d+\.?\d*)%', line)
            if m:
                pct = min(int(float(m.group(1))), 99)
                _push_event(load_id, {
                    'stage': 'download', 'progress': pct,
                    'message': f'Downloading... {pct}%',
                })
        proc.wait()

        if proc.returncode != 0:
            _push_event(load_id, {
                'status': 'error',
                'message': 'Download failed. Track may be unavailable or require login.',
            })
            return

        wavs = list(dl_dir.glob('*.wav'))
        if not wavs:
            _push_event(load_id, {'status': 'error', 'message': 'No audio file produced.'})
            return

        with _jobs_lock:
            _jobs[load_id]['wav_path'] = str(wavs[0])

        _push_event(load_id, {'status': 'done', 'audio_url': f'/api/audio/{load_id}'})

    except Exception as exc:
        _push_event(load_id, {'status': 'error', 'message': str(exc)})


# ─── Worker: Demucs ───────────────────────────────────────────────────────────

def _run_stems(analyze_id: str, wav_path: Path, stems_dir: Path):
    """Run Demucs with time-based progress (tqdm output isn't line-buffered).
    Returns stem dict on success, or None (error event already pushed)."""
    stems_dir.mkdir(parents=True, exist_ok=True)
    stop_evt = threading.Event()
    start_t = time.time()

    def _progress():
        while not stop_evt.is_set():
            elapsed = time.time() - start_t
            if elapsed < 20:
                msg = 'Separating stems (downloading model on first run ~1 GB)...'
                pct = 2
            else:
                pct = min(int((elapsed - 20) / 130 * 93) + 2, 95)
                msg = f'Separating stems... {pct}%'
            _push_event(analyze_id, {'stage': 'stems', 'progress': pct, 'message': msg})
            stop_evt.wait(timeout=4)

    t = threading.Thread(target=_progress, daemon=True)
    t.start()

    cmd = ['python3', '-m', 'demucs', '--name', 'htdemucs',
           '--out', str(stems_dir), str(wav_path)]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    proc.wait()
    stop_evt.set()

    if proc.returncode != 0:
        _push_event(analyze_id, {'status': 'error', 'message': 'Demucs stem separation failed.'})
        return None

    stems = {}
    for name in ('drums', 'bass', 'vocals', 'other'):
        p = stems_dir / 'htdemucs' / wav_path.stem / f'{name}.wav'
        if not p.exists():
            found = list(stems_dir.glob(f'**/{name}.wav'))
            if found:
                p = found[0]
        if p.exists():
            stems[name] = p

    if not stems:
        _push_event(analyze_id, {'status': 'error', 'message': 'Demucs produced no stem files.'})
        return None

    return stems


# ─── Worker: analyze ──────────────────────────────────────────────────────────

def _analyze_worker(analyze_id: str, load_id: str, stem: str,
                    start_sec, end_sec, description: str):
    try:
        with _jobs_lock:
            load_job = _jobs.get(load_id, {})
        wav_str = load_job.get('wav_path')

        if not wav_str or not Path(wav_str).exists():
            _push_event(analyze_id, {
                'status': 'error',
                'message': 'Source audio not found. Reload the track.',
            })
            return

        wav_path = Path(wav_str)
        track_slug = pipeline.safe_slug(wav_path.stem)
        track_out = OUTPUT_ROOT / track_slug
        track_out.mkdir(parents=True, exist_ok=True)
        stems_dir = WORKSPACE / 'stems'
        stems_dir.mkdir(exist_ok=True)

        # ── Step 1: Stems ─────────────────────────────────────────────────────
        cached = _stems_cached(wav_path, stems_dir)
        if cached:
            _push_event(analyze_id, {
                'stage': 'stems', 'progress': 100,
                'message': 'Stems cached — skipping Demucs',
            })
            stems = cached
        else:
            stems = _run_stems(analyze_id, wav_path, stems_dir)
            if stems is None:
                return  # error already pushed

        _push_event(analyze_id, {'stage': 'stems', 'progress': 100, 'message': 'Stems ready'})

        if stem == 'full':
            analysis_audio = wav_path
        else:
            if stem not in stems:
                stem = 'other'
            analysis_audio = stems[stem]

        # ── Step 2: Feature analysis ──────────────────────────────────────────
        _push_event(analyze_id, {
            'stage': 'analyze', 'progress': 72,
            'message': 'Finding onset and extracting features...',
        })
        features = pipeline.analyze_audio(str(analysis_audio), start_sec, end_sec)
        _push_event(analyze_id, {
            'stage': 'analyze', 'progress': 90,
            'message': 'Feature extraction complete',
        })

        # ── Step 3: Spectrogram ───────────────────────────────────────────────
        _push_event(analyze_id, {
            'stage': 'spectrogram', 'progress': 92,
            'message': 'Rendering spectrogram...',
        })
        spec_path = track_out / f'spectrogram_{analyze_id}.png'
        onset_sec = features['onset_window']['absolute_onset_time_sec']
        pipeline.generate_spectrogram(
            str(analysis_audio), str(spec_path),
            onset_sec, onset_sec + pipeline.NOTE_WINDOW_SEC,
        )

        result = {
            'track': {
                'title': wav_path.stem,
                'target_sound_description': description,
                'stem_analyzed': stem,
                'time_range': {'start_seconds': start_sec, 'end_seconds': end_sec},
            },
            'analysis': features,
        }
        (track_out / f'analysis_{analyze_id}.json').write_text(json.dumps(result, indent=2))

        with _jobs_lock:
            _jobs[analyze_id]['spec_path'] = str(spec_path)
            _jobs[analyze_id]['result'] = result

        _push_event(analyze_id, {
            'status': 'done',
            'spectrogram_url': f'/api/spectrogram/{analyze_id}',
            'result_url':      f'/api/result/{analyze_id}',
        })

    except Exception as exc:
        _push_event(analyze_id, {'status': 'error', 'message': str(exc)})


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


# ── Load ──────────────────────────────────────────────────────────────────────

@app.route('/api/load', methods=['POST'])
def api_load():
    data = request.get_json(force=True)
    url = (data.get('url') or '').strip()
    if not url:
        return jsonify({'error': 'url required'}), 400

    load_id = _job_id(url)

    # Already done in this session?
    with _jobs_lock:
        ex = _jobs.get(load_id)
    if ex and ex['status'] == 'done' and ex.get('wav_path'):
        return jsonify({'job_id': load_id, 'status': 'done',
                        'audio_url': f'/api/audio/{load_id}'})
    if ex and ex['status'] == 'running':
        return jsonify({'job_id': load_id, 'status': 'started'})

    # Disk cache from a previous app session?
    dl_dir = WORKSPACE / 'downloads' / load_id
    wavs = list(dl_dir.glob('*.wav')) if dl_dir.exists() else []
    if wavs:
        job = _new_job(load_id, 'load')
        with _jobs_lock:
            _jobs[load_id]['wav_path'] = str(wavs[0])
            _jobs[load_id]['status'] = 'done'
        return jsonify({'job_id': load_id, 'status': 'done',
                        'audio_url': f'/api/audio/{load_id}'})

    _new_job(load_id, 'load')
    with _jobs_lock:
        _jobs[load_id]['status'] = 'running'
    threading.Thread(target=_load_worker, args=(load_id, url), daemon=True).start()
    return jsonify({'job_id': load_id, 'status': 'started'})


@app.route('/api/load/<load_id>/stream')
def load_stream(load_id):
    return _sse_response(_sse_stream(load_id))


@app.route('/api/audio/<load_id>')
def serve_audio(load_id):
    with _jobs_lock:
        job = _jobs.get(load_id, {})
    wav = job.get('wav_path')
    if not wav or not Path(wav).exists():
        dl_dir = WORKSPACE / 'downloads' / load_id
        wavs = list(dl_dir.glob('*.wav')) if dl_dir.exists() else []
        if not wavs:
            return 'Not found', 404
        wav = str(wavs[0])
    return send_file(wav, mimetype='audio/wav', conditional=True)


# ── Analyze ───────────────────────────────────────────────────────────────────

@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    data = request.get_json(force=True)
    load_id     = data.get('load_id', '')
    description = (data.get('description') or 'target sound').strip()
    stem        = data.get('stem', 'other')
    start_sec   = float(data['start_sec']) if data.get('start_sec') is not None else None
    end_sec     = float(data['end_sec'])   if data.get('end_sec')   is not None else None

    analyze_id = _job_id(load_id, stem, str(start_sec), str(end_sec))

    with _jobs_lock:
        ex = _jobs.get(analyze_id)
    if ex and ex['status'] == 'done':
        return jsonify({'job_id': analyze_id, 'status': 'done'})
    if ex and ex['status'] == 'running':
        return jsonify({'job_id': analyze_id, 'status': 'started'})

    _new_job(analyze_id, 'analyze')
    with _jobs_lock:
        _jobs[analyze_id]['status'] = 'running'
    threading.Thread(
        target=_analyze_worker,
        args=(analyze_id, load_id, stem, start_sec, end_sec, description),
        daemon=True,
    ).start()
    return jsonify({'job_id': analyze_id, 'status': 'started'})


@app.route('/api/analyze/<analyze_id>/stream')
def analyze_stream(analyze_id):
    return _sse_response(_sse_stream(analyze_id))


@app.route('/api/spectrogram/<analyze_id>')
def serve_spectrogram(analyze_id):
    with _jobs_lock:
        job = _jobs.get(analyze_id, {})
    spec = job.get('spec_path')
    if spec and Path(spec).exists():
        return send_file(spec, mimetype='image/png')
    return 'Not found', 404


@app.route('/api/result/<analyze_id>')
def serve_result(analyze_id):
    with _jobs_lock:
        job = _jobs.get(analyze_id, {})
    result = job.get('result')
    if result:
        return jsonify(result)
    return jsonify({'error': 'Result not ready'}), 404


# ─── Start ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    (WORKSPACE / 'downloads').mkdir(exist_ok=True)
    (WORKSPACE / 'stems').mkdir(exist_ok=True)
    print('\n  M8 Patch Finder  →  http://localhost:5000\n')
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)
