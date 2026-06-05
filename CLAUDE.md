# M8 Patch Finder — Claude Interpretation Guide

This project analyzes audio from SoundCloud/YouTube and produces structured feature data for reverse-engineering synthesizer patches on the **Dirtywave M8** tracker.

When a user pastes an `analysis.json` file and/or attaches a `spectrogram.png`, your job is to:

1. Read the analysis data carefully
2. Recommend the best M8 synth engine for the sound
3. Provide specific parameter values for that engine
4. Explain the reasoning briefly

---

## Workflow

The user will provide one or both of:
- **analysis.json** — structured feature extraction output from `analyze.py`
- **spectrogram.png** — mel spectrogram + chromagram image

Standard prompt: *"Recommend an M8 patch to imitate: [sound description]"*

Use both sources together. The JSON gives you precise numeric features; the spectrogram lets you see harmonic density, filter movement, transients, and envelope shape visually.

---

## Engine Selection Guide

Pick the engine first — wrong engine, wrong parameters.

| Signal | Engine to consider |
|---|---|
| Rich harmonics, classic analog feel, subtractive character | WAVSYNTH |
| Complex timbre, hard to place — FM-ish, formant, metallic, digital | MACROSYNTH |
| Clearly FM-style bell, organ, electric piano, metallic, inharmonic | FM |
| Plucked/strummed physical model, Karplus-Strong-like | MACROSYNTH (PLCK model) |
| Choir, vowel, formant sweep | MACROSYNTH (MALE, CHOR, GWYN) |
| Pad with slow attack, evolving texture | WAVSYNTH or MACROSYNTH |
| Bass with sub content | WAVSYNTH (SAW or PUL) |
| Drum/percussion synth texture | MACROSYNTH (percussive models) |

**Tie-breaker**: if harmonic_ratio > 0.75 and harmonic_count_estimate > 6, lean WAVSYNTH. If harmonic_count is low but the sound is bright and complex, lean MACROSYNTH. FM metallic character is usually obvious from the spectrogram (inharmonic sidebands).

---

## WAVSYNTH Parameters

WAVSYNTH is a classic waveform oscillator → filter → amp chain.

### Oscillator

| Param | Range | Notes |
|---|---|---|
| WAVE | 0–14 | Waveform shape (see table below) |
| SIZE | 00–FF | Period/size of waveform |
| MULT | 00–FF | Pitch multiplier (coarse) |
| WARP | 00–FF | Waveform distortion/warping |
| SHIFT | 00–FF | Phase shift |

Waveform values:
- `00` SIN — sine wave (fewest harmonics, dark/pure)
- `01` SAW — sawtooth (all harmonics, bright, most common for leads/bass)
- `02` SAW2 — alternate saw variant
- `03` TRI — triangle (odd harmonics only, softer than saw)
- `04` TRI2 — alternate triangle
- `05` PUL — pulse/square (odd harmonics, hollow)
- `06` PUL2 — alternate pulse
- `07` NAR — narrow pulse (thin, buzzy)
- `08` NAR2 — alternate narrow pulse
- `09`–`0E` — CHE, SQU, MRL variants

**Mapping from analysis:**
- `brightness: dark` → SIN or TRI, low WARP
- `brightness: warm` → TRI or SAW with low CUT
- `brightness: bright` → SAW or PUL, higher CUT
- `harmonic_profile: rich_saw` → WAVE=01 (SAW)
- `harmonic_profile: simple_sine_triangle` → WAVE=00 (SIN) or 03 (TRI)

---

## MACROSYNTH Parameters

MACROSYNTH is based on Mutable Instruments Braids — a multi-algorithm synth. The model determines the synthesis type; TIMB and COLR morph the timbre within that model.

### Core Params

| Param | Range | Notes |
|---|---|---|
| MODEL | (see below) | Synthesis algorithm |
| TIMB | 00–FF | Timbre — varies by model |
| COLR | 00–FF | Color — varies by model |
| DEGRADE | 00–FF | Bit crushing / sample rate reduction |
| REDUX | 00–FF | Sample rate reduction |

### Model Selection

| Model | Character | When to use |
|---|---|---|
| CSAW | Virtual analog, classic saw | Leads, basses with extra edge |
| ^OON | Morphing between waveforms | Evolving pads |
| ZTRI | Tri-based morphing | Soft leads |
| ZSAW | Saw-based morphing | Aggressive leads |
| ///// | Slope/ramp morphing | Unusual textures |
| WTBT | Wavetable, bass-focused | Sub bass, growl bass |
| WTSQ | Wavetable, square-ish | Hollow tones |
| WTSAW | Wavetable, saw-ish | Rich moving leads |
| WTSK | Wavetable, silky | Smooth pads |
| WTCH | Wavetable, chest | Warm pads |
| WTCL | Wavetable, clean | Neutral evolving |
| WTF1–WTF4 | Wavetable formant variants | Vocal-adjacent textures |
| NZ | Noise | Wind, breath, texture layer |
| FB-OSC | Feedback oscillator | Harsh, screaming tones |
| CLKN / CLCK | Clock noise | Industrial texture |
| STRG | String model | Bowed/plucked strings |
| PLTE | Plate resonator | Metallic resonance |
| BOWD | Bowed string | Slow attack string |
| BLOW | Flute/blow model | Breathy, airy |
| FLUT | Flute | Breathy pitched |
| BELL | Bell | Metallic, inharmonic bell |
| MLLT | Mallet | Marimba/xylophone |
| SPCL | Speech | Robotic vowels |
| MALE | Male voice formant | Choral, vowel |
| CHOR | Choir | Wide choral pad |
| GWYN | Gwyn (formant) | Specific vowel formant |
| HARP | Harp | Plucked string |
| EPNO | Electric piano | EP-style |
| ORGN | Organ | Hammond-like |
| HARM | Harmonics | Additive partial control |
| FM | FM synthesis | Bell, metallic, EP |
| FBFM | Feedback FM | Aggressive FM |
| WTFM | Wavetable FM | Moving FM |
| PLCK | Pluck | Karplus-Strong pluck |
| BASS | Bass | Synth bass model |
| DIGI | Digital | Harsh digital |
| DIST | Distorted | Clipped/driven |
| CRUS | Crushed | Bit-crushed |
| PRTL | Particle | Granular-adjacent |
| QPSK | QPSK modulation | Digital noise texture |

**Mapping from analysis:**
- `envelope.type: plucked` + `pitch_stability > 0.7` → PLCK or HARP
- `harmonic_profile: noisy_or_complex` + bright → FM or FBFM
- `envelope.type: pad` + `lfo_detected: true` → WTSK, WTCH, or ^OON with LFO on TIMB
- `envelope.type: sustained` + mid brightness → CSAW or ZTRI

---

## FM Parameters

4-operator FM synthesis. Each operator is either a Carrier (produces sound) or a Modulator (shapes another operator's frequency).

| Param | Range | Notes |
|---|---|---|
| ALG | 00–0B | Algorithm — routing of 4 operators |
| OP A RATIO | 00–FF | Frequency ratio of operator A |
| OP A FINE | 00–FF | Fine tune |
| OP A LEVEL | 00–FF | Output/modulation level |
| OP A FB | 00–FF | Self-feedback (only on some algorithms) |
| (same for B, C, D) | | |

**Algorithm guide:**
- ALG 00: all operators in series (maximum modulation complexity, harsh)
- ALG 0B: all operators in parallel (additive, clean bell/organ)
- Mid ALGs: branches — some carriers with dedicated modulators

**Mapping from analysis:**
- `harmonic_count_estimate > 8` + inharmonic look in spectrogram → FM with higher ALG index, high modulator LEVEL
- Bell/metallic → ALG with 2+ carriers, odd RATIO values (e.g. 3, 5, 7)
- Electric piano → ALG with 2 operators, RATIO 1:1, moderate LEVEL
- Bright FM bass → RATIO 1 carrier + RATIO 2 modulator, high LEVEL

---

## Shared Parameters (all engines)

### Filter

| Param | Values | Notes |
|---|---|---|
| FLT | LP24/LP12/LP6/HP24/HP12/HP6/BP24/BP12/EQ | Filter type |
| CUT | 00–FF | Cutoff frequency (00=closed, FF=fully open) |
| RES | 00–FF | Resonance (above C0 can self-oscillate) |

**Mapping:**
- `brightness: dark` → LP24, CUT ~40–70
- `brightness: warm` → LP12, CUT ~80–A0
- `brightness: bright` → LP24, CUT ~C0–E0
- `brightness: very_bright` → LP24, CUT FF (fully open)
- `rolloff_85pct_hz` gives a direct clue: Hz → approximate CUT value scales roughly 0–20kHz → 00–FF

### AMP Envelope

| Param | Range | Notes |
|---|---|---|
| VOL | 00–FF | Output volume |
| PAN | 00–FF | Pan (00=left, 80=center, FF=right) |
| A | 00–FF | Attack |
| H | 00–FF | Hold |
| D | 00–FF | Decay |
| S | 00–FF | Sustain level |
| R | 00–FF | Release |

**Mapping from `analysis.envelope`:**

The M8's envelope values are exponential, not linear ms values. Use these rough conversions:

| attack_ms | A value |
|---|---|
| <5 | 00 |
| 5–20 | 00–05 |
| 20–100 | 05–20 |
| 100–500 | 20–60 |
| >500 | 60–FF |

| decay_ms | D value |
|---|---|
| <50 | 00–10 |
| 50–200 | 10–40 |
| 200–500 | 40–80 |
| >500 | 80–FF |

| sustain_level | S value |
|---|---|
| 0.0–0.1 | 00–1A |
| 0.1–0.3 | 1A–4D |
| 0.3–0.6 | 4D–99 |
| 0.6–1.0 | 99–FF |

| release_ms | R value |
|---|---|
| <50 | 00–10 |
| 50–200 | 10–40 |
| 200–1000 | 40–A0 |
| >1000 | A0–FF |

**Envelope types:**
- `plucked` → A=00, D=20–60, S=00, R=10–30
- `pad` → A=60–C0, D=30, S=C0, R=80–C0
- `sustained` → A=05–20, D=20, S=B0–E0, R=40–80
- `percussive` → A=00, D=10–30, S=00, R=05–20

### LFO

| Param | Values | Notes |
|---|---|---|
| SHAPE | TRI/SIN/RSIN/SAW/SAW2/SQU/RND/DRND | LFO waveform |
| DEST | (engine-specific) | Modulation destination |
| FREQ | 00–FF | LFO rate |
| AMT | 00–FF | Modulation depth |
| RET | ON/OFF | Retrigger on note |
| PHA | 00–FF | Phase offset |

**Mapping:**
- `lfo_detected: true`, `lfo_rate_hz` → FREQ ≈ lfo_rate_hz * 5 (rough guideline; M8 LFO is not Hz-calibrated)
- Vibrato → DEST=PITCH, SHAPE=SIN or TRI, low AMT
- Filter movement → DEST=CUTOFF, AMT moderate
- Tremolo → DEST=VOL, SHAPE=SIN

---

## Output Format

Always structure your patch recommendation like this:

```
ENGINE: [WAVSYNTH / MACROSYNTH / FM]

Why: [1–2 sentence explanation of why this engine fits the sound]

PARAMETERS:
  [Oscillator section]
    WAVE/MODEL: [value]
    [other osc params]

  FILTER:
    FLT:  [type]
    CUT:  [hex]
    RES:  [hex]

  AMP:
    VOL:  [hex]
    PAN:  80
    A:    [hex]
    H:    00
    D:    [hex]
    S:    [hex]
    R:    [hex]

  LFO:
    SHAPE: [shape or OFF]
    DEST:  [destination or N/A]
    FREQ:  [hex]
    AMT:   [hex]

NOTES:
  [Any caveats, alternative approaches, or suggested tweaks to dial in further]
```

Always give hex values (00–FF) for numeric params. If uncertain between two values, give a range like `40–60` and say which direction to move for brighter/darker/longer/shorter.

---

## Reading the Spectrogram

The spectrogram has two panels:

**Top — Mel Spectrogram:** Energy over time, frequency on Y axis (mel scale, 0–8kHz).
- Dense bright bands = rich harmonics
- Clean single bands = simple/pure waveform
- Blurred/smeared = reverb or noisy character
- Bright horizontal lines (at multiples of a fundamental) = strong harmonic series → SAW/SQUARE character
- Scattered energy = noisy, FM, or complex model

**Bottom — Chromagram:** Which pitch classes are active over time.
- Single bright row = monophonic, stable pitch
- Multiple rows = chords, detuning, or inharmonic content
- Rapidly shifting rows = pitch modulation or LFO on pitch

Use the chromagram together with `pitch.vibrato_detected` and `modulation.lfo_detected` to determine if LFO on pitch is needed.
