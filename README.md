# M8 Patch Finder

Analyze a song from SoundCloud or YouTube and get Dirtywave M8 synth patch recommendations for any sound in the mix.

## How it works

1. **Load** — paste a SoundCloud or YouTube URL into the web app and download the track
2. **Configure** — play the audio, drag to select the section where your target sound lives, describe it, pick a stem
3. **Analyze** — the app separates stems with Demucs, extracts spectral/pitch/envelope features with librosa, and generates a spectrogram
4. **Get the patch** — copy the analysis JSON + download the spectrogram, then paste both into a Claude Code session opened in this folder

No AI API key required — all analysis runs locally. Claude interprets the results using `CLAUDE.md` as its reference guide.

---

## Setup

### Requirements

- Python 3.9+
- `ffmpeg` (installed via Homebrew: `brew install ffmpeg`)

### Install

```bash
cd /Users/davidolson/Documents/m8-patch-finder
pip3 install -r requirements.txt
```

> **First run note:** Demucs downloads a ~1 GB neural network model the first time it separates stems. This is a one-time download that happens automatically.

---

## Running the app

```bash
cd /Users/davidolson/Documents/m8-patch-finder
python3 app.py
```

Then open **http://localhost:5000** in your browser.

---

## Workflow

### Step 1 — Load a track

Paste a SoundCloud or YouTube URL into the input field and click **LOAD**. The download progress streams live. When it finishes, the waveform appears.

> Tracks already downloaded in a previous session load instantly from disk cache.

### Step 2 — Configure

- **Play** the audio to locate your target sound
- **Drag across the waveform** to select the region containing it — this sets the analysis window. The crop timestamps update in real time. If you skip this, the full track is analyzed.
- **Describe the target sound** — e.g. *"the plucked lead synth in the chorus"*
- **Choose a stem** — pick which Demucs separation layer to analyze:

| Stem | Use for |
|------|---------|
| OTHER (default) | Synths, guitars, pads — anything that isn't drums, bass, or vocals |
| BASS | Bass synth, sub bass, bass guitar |
| VOCALS | Vocal lead, choir, voice synthesis |
| DRUMS | Percussion, kick, snare |
| FULL | No stem separation — analyze the full mix |

### Step 3 — Analyze

Click **ANALYZE**. Three steps stream progress live:

1. **STEMS** — Demucs separates the track (1–3 min on first run; instant if cached from a prior session)
2. **ANALYZE** — onset detection, spectral/pitch/envelope/harmonic feature extraction
3. **SPECGRAM** — mel spectrogram + chromagram image rendered

When complete, the spectrogram image and full analysis JSON appear.

### Step 4 — Get your M8 patch

1. Click **DOWNLOAD JSON** and **DOWNLOAD SPECTROGRAM** to save both files
2. Open a new Claude Code session in this project folder:
   ```bash
   cd /Users/davidolson/Documents/m8-patch-finder
   claude
   ```
3. Paste the JSON contents into the session
4. Attach the spectrogram PNG as an image
5. Prompt: `"Recommend an M8 patch to imitate: [your sound description]"`

Claude reads `CLAUDE.md` automatically (it's the project context file) and outputs a recommended M8 engine with specific hex parameter values for each setting.

---

## Troubleshooting

**Waveform doesn't play in the browser**
The waveform player uses the downloaded WAV file served locally — it does not stream from SoundCloud or YouTube. If the waveform appears but playback doesn't start, try clicking directly on the waveform rather than the play button. Large files (> 100 MB) may take a few seconds to decode.

**yt-dlp download fails**
Some SoundCloud tracks require a logged-in account. Try a YouTube link for the same track instead — YouTube links work more reliably.

**Demucs is slow / stuck at 0%**
On the very first run, Demucs silently downloads its ~1 GB model before separating. The progress bar will sit near 0% for several minutes. This is normal and only happens once.

**Poor stem separation**
Demucs works best on commercially produced, mixed music. Live recordings or heavily distorted tracks may bleed between stems. Use the **FULL** stem option as a fallback.

**No pitch detected in results**
The target sound may be noise-based or atonal (e.g. a texture pad, a percussion hit). The analysis still works — `pitch.note` will read `unpitched` and Claude will use spectral and harmonic features instead.

**"Back" button / running a second analysis**
Click **← BACK** in the results panel to return to the waveform. You can adjust the crop region, change the stem, or update the description and run another analysis. Cached stems are reused automatically.
