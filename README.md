# M8 Patch Finder

Analyze a song from SoundCloud or YouTube and get Dirtywave M8 synth patch recommendations for any sound in the mix.

## How it works

1. `analyze.py` downloads the track, separates stems with [Demucs](https://github.com/facebookresearch/demucs), extracts spectral/temporal features with librosa, and generates a spectrogram image.
2. You paste the output JSON + attach the spectrogram PNG into a Claude Code session.
3. Claude reads `CLAUDE.md` (auto-loaded) and outputs specific M8 engine + parameter recommendations.

No AI API key required — all analysis runs locally.

---

## Setup

### Requirements

- Python 3.9+
- `ffmpeg` installed and on your PATH ([ffmpeg.org](https://ffmpeg.org/download.html))

### Install

```bash
cd /path/to/m8-patch-finder
pip install -r requirements.txt
```

> **Note:** Demucs downloads a ~1 GB neural network model on first run. This happens automatically.

---

## Usage

```bash
python analyze.py <url> "<sound description>"
```

### Examples

```bash
# Isolate the "other" stem (default — synths, guitar, anything not drums/bass/vocals)
python analyze.py "https://soundcloud.com/artist/track" "the plucked lead synth in the chorus"

# Analyze only the bass stem
python analyze.py "https://youtu.be/VIDEO_ID" "the growling synth bass" --stem bass

# Analyze a specific time range (e.g. the chorus only)
python analyze.py "https://youtu.be/VIDEO_ID" "the pad in the breakdown" --start 1:20 --end 2:00

# Analyze the full mix (no stem separation)
python analyze.py "https://soundcloud.com/artist/track" "the whole texture" --stem full
```

### Stem options

| `--stem` | What it contains |
|---|---|
| `other` (default) | Synths, guitars, everything not drums/bass/vocals |
| `bass` | Bass guitar, sub bass, bass synth |
| `vocals` | Vocals |
| `drums` | Drums, percussion |
| `full` | No separation — full mix |

### Time range tip

If the sound you want only appears in a specific section (chorus, drop, bridge), use `--start` and `--end` to focus the analysis. This gives much cleaner feature extraction than analyzing a 4-minute track where the target sound appears for 30 seconds.

---

## Getting M8 patch recommendations

After `analyze.py` finishes it prints the paths to two output files:

```
Done.
  JSON:        output/Track_Name/analysis.json
  Spectrogram: output/Track_Name/spectrogram.png
```

Then:

1. Open a new Claude Code session in this project folder:
   ```bash
   cd /path/to/m8-patch-finder
   claude
   ```
2. Paste the full contents of `analysis.json`
3. Attach `spectrogram.png` as an image
4. Prompt: `"Recommend an M8 patch to imitate: [your sound description]"`

Claude will read `CLAUDE.md` automatically (it's the project context file) and output an engine recommendation with specific hex parameter values for each M8 parameter.

---

## Output files

Each analysis run creates a folder under `output/` named after the track:

```
output/
  Track_Name/
    analysis.json     ← paste into Claude
    spectrogram.png   ← attach as image in Claude
  _workspace/         ← intermediate files (downloads, stems) — safe to delete
```

---

## Troubleshooting

**yt-dlp fails:** Some tracks on SoundCloud require a free account. Try passing cookies:
```bash
yt-dlp --cookies-from-browser firefox <url>
```

**Demucs is slow:** It runs on CPU by default. If you have a compatible GPU, add `--device cuda` (NVIDIA) or `--device mps` (Apple Silicon) to the demucs call inside `analyze.py`.

**Poor stem separation:** Demucs works best on produced, mixed music. Live recordings or heavily distorted tracks may bleed between stems. Use `--stem full` as a fallback.

**"No pitch detected":** The target sound may be noise-based or atonal. The analysis still works — `pitch.note` will read `unpitched` and Claude will use spectral features instead to guide synthesis choices.
