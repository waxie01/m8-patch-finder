# M8 Patch Finder — Outstanding Work

Session handoff document. A new Claude Code session opened in this folder can pick up from here.

---

## Current state

The web GUI is fully built and working at `python3 app.py` → http://localhost:5000.
The three-section Phosphor Tracker UI (Load → Configure → Analyze) is complete and committed.
The CLI (`python3 analyze.py`) is still intact but no longer the primary interface.

Key files:
- `app.py` — Flask server, SSE progress streaming, background workers for yt-dlp + Demucs
- `analyze.py` — audio analysis pipeline (imported by app.py; also works standalone as CLI)
- `templates/index.html` — single-page app shell
- `static/style.css` — Phosphor Tracker dark theme
- `static/app.js` — frontend state machine, WaveSurfer.js waveform, SSE handlers
- `CLAUDE.md` — M8 engine parameter reference (auto-loads in Claude Code sessions)

---

## Item 1 — Download buttons for JSON and spectrogram

**What's missing:** After analysis completes, the results panel shows a COPY JSON button (clipboard only) and the spectrogram image. There are no download buttons to save the files locally.

**What to add:**
- **DOWNLOAD JSON** button next to COPY JSON — triggers a browser file download of the analysis JSON
- **DOWNLOAD SPECTROGRAM** button below or over the spectrogram image — triggers a browser file download of the PNG

**Implementation approach:**

Option A (backend — cleanest): Add `Content-Disposition: attachment` header to the existing serve endpoints in `app.py`:
```python
@app.route('/api/download/result/<analyze_id>')
def download_result(analyze_id):
    # same as serve_result but forces download
    ...
    return jsonify(result), 200, {
        'Content-Disposition': f'attachment; filename="analysis_{analyze_id}.json"'
    }

@app.route('/api/download/spectrogram/<analyze_id>')
def download_spectrogram(analyze_id):
    return send_file(spec, as_attachment=True,
                     download_name=f'spectrogram_{analyze_id}.png')
```

Option B (frontend — simpler, no new routes): In `app.js`, use Blob URLs after the result loads:
```javascript
// For JSON:
const blob = new Blob([resultJson.textContent], {type: 'application/json'});
const a = document.createElement('a');
a.href = URL.createObjectURL(blob);
a.download = `analysis_${analyzeId}.json`;
a.click();

// For spectrogram:
// Just set <a href="/api/spectrogram/<id>" download="spectrogram.png">
```

Option B is simpler. Add two buttons to `#json-panel` and `#spectrogram-panel` in `index.html` and wire them in `app.js`.

---

## Item 2 — Audio playback / waveform interaction not working

**Symptom:** User reported they can't play or interact with the waveform. They asked if it's because of a SoundCloud link.

**It is NOT a SoundCloud restriction.** The tool downloads the audio as a local WAV file and serves it at `/api/audio/<load_id>`. WaveSurfer.js loads from that local URL, not from SoundCloud directly.

**Likely causes to investigate:**

1. **WAV file too large for browser decode** — A 3-minute stereo WAV at 44.1kHz is ~30–50 MB. WaveSurfer v7 decodes via Web Audio API in-browser. Most browsers handle this fine but can be slow. Check the browser console for errors (`AudioContext` decode failures show up there).

2. **WaveSurfer container height** — If the `#waveform` div has zero computed height before WaveSurfer initializes, the canvas renders invisible. The `height: 82` option is set in `WaveSurfer.create()` which should override this, but worth verifying in DevTools.

3. **Range request handling** — `send_file(conditional=True)` in Flask/Werkzeug handles HTTP 206 Partial Content. Verify the response headers include `Accept-Ranges: bytes` by opening `http://localhost:5000/api/audio/<load_id>` directly in the browser — it should prompt a download. If it returns 404 or 500, the WAV path isn't resolving correctly.

4. **WaveSurfer interaction area** — The drag-to-select region uses `RegionsPlugin.enableDragSelection()`. If the waveform renders but dragging doesn't create a region, check that the `#waveform` div isn't covered by another element (the `#scanlines` overlay is `pointer-events: none` so it shouldn't block, but worth checking).

**Debugging steps:**
- Open browser DevTools → Console after loading a track. Any WaveSurfer errors will appear there.
- Check Network tab: confirm the `/api/audio/<id>` request returns 200 or 206 with audio content.
- Try clicking directly on the waveform (not the PLAY button) to seek — if that works, the issue is isolated to the button event handler.

---

## Item 3 — Vercel hosting

**Important constraint:** Vercel will NOT work for this app without major architectural changes.

**Why:**
- Vercel runs Python as serverless functions with a **10-second timeout** (free tier) or 60 seconds (paid). Demucs takes **1–3 minutes** — far beyond these limits.
- Vercel functions are **stateless with no persistent filesystem**. Downloaded WAV files, Demucs stem outputs, and the ~1 GB Demucs model weights cannot be stored between requests.
- The SSE (Server-Sent Events) streaming approach doesn't work on Vercel's serverless architecture either.

**Realistic hosting alternatives:**

| Option | Cost | Effort | Notes |
|--------|------|--------|-------|
| **Run locally** (current) | Free | None | Best for personal use |
| **Railway.app** | ~$5/mo | Low | Persistent disk, no timeout limits, Docker-based, easy GitHub deploy |
| **Render.com** | Free tier / ~$7/mo | Low | Similar to Railway, supports long-running processes |
| **Fly.io** | ~$3–5/mo | Medium | More control, persistent volumes |
| **Docker on a VPS** (DigitalOcean, etc.) | ~$6/mo | Medium | Full control |

**Recommended path:** Railway.app — it supports long-running Python processes, has a GitHub integration similar to Vercel, and the free tier may cover occasional personal use. It would need a `Dockerfile` or `railway.toml` config, and a writable volume mount for the `output/` directory.

If the user wants to pursue this, the approach is:
1. Add a `Dockerfile` that installs ffmpeg + Python deps and runs `python3 app.py`
2. Create a Railway project linked to the `waxie01/m8-patch-finder` GitHub repo
3. Add a persistent volume mounted at `/app/output` for WAV files and analysis results
4. Note: Demucs model (~1 GB) will re-download on each fresh container deploy unless it's baked into the Docker image or stored on the volume

---

## How to use this file in a new session

Open Claude Code in this project folder:
```bash
cd /Users/davidolson/Documents/m8-patch-finder
claude
```
Then say: *"Read NEXT_STEPS.md and let's work through the outstanding items."*

Items 1 and 2 are straightforward code changes. Item 3 requires a conversation about which hosting option to pursue before any code is written.
