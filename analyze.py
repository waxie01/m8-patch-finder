#!/usr/bin/env python3
"""
M8 Patch Finder - Audio analysis pipeline
Extracts synthesis-relevant features for M8 patch design.

Usage:
  python analyze.py <url> "<sound description>"
  python analyze.py <url> "<sound description>" --start 0:45 --end 1:15
  python analyze.py <url> "<sound description>" --stem bass

Arguments:
  url           SoundCloud or YouTube URL
  description   What sound to target, e.g. "plucked lead synth in chorus"
  --start       Analysis start time (MM:SS or seconds)
  --end         Analysis end time (MM:SS or seconds)
  --stem        Which Demucs stem to analyze: other (default), vocals, bass, drums, full
"""

import sys
import re
import json
import argparse
import subprocess
from pathlib import Path

import numpy as np
import librosa
import librosa.display
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


SPEC_HOP = 512  # librosa default hop length, used consistently across all feature calls


def parse_time(t):
    if ':' in t:
        m, s = t.split(':', 1)
        return int(m) * 60 + float(s)
    return float(t)


def safe_slug(name):
    return re.sub(r'[^\w\-.]', '_', name)[:60].strip('_')


def download_audio(url, dl_dir):
    print("[1/4] Downloading audio...")
    r = subprocess.run(
        ['python3', '-m', 'yt_dlp', '-x', '--audio-format', 'wav', '--audio-quality', '0',
         '--no-playlist', '-o', str(dl_dir / '%(title)s.%(ext)s'), url],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        sys.exit(f"yt-dlp error:\n{r.stderr}")
    wav_files = list(dl_dir.glob('*.wav'))
    if not wav_files:
        sys.exit("yt-dlp produced no WAV file.")
    return wav_files[0]


def separate_stems(wav_path, stems_dir):
    print("[2/4] Separating stems with Demucs (first run downloads ~1 GB model)...")
    r = subprocess.run(
        ['python3', '-m', 'demucs', '--name', 'htdemucs',
         '--out', str(stems_dir), str(wav_path)],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        sys.exit(f"Demucs error:\n{r.stderr}")

    stems = {}
    for name in ('drums', 'bass', 'vocals', 'other'):
        # htdemucs output path
        p = stems_dir / 'htdemucs' / wav_path.stem / f'{name}.wav'
        if not p.exists():
            # fallback: search recursively
            found = list(stems_dir.glob(f'**/{name}.wav'))
            if found:
                p = found[0]
        if p.exists():
            stems[name] = p

    if not stems:
        sys.exit("Demucs produced no stem files.")
    return stems


def estimate_adsr(y, sr):
    frame_len = max(int(0.01 * sr), 64)
    hop = frame_len // 2
    rms = librosa.feature.rms(y=y, frame_length=frame_len, hop_length=hop)[0]

    if rms.max() < 1e-6:
        return {'attack_ms': 0, 'decay_ms': 0, 'sustain_level': 0,
                'release_ms': 0, 'type': 'silent'}

    rms_n = rms / rms.max()
    t_ms = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop) * 1000
    n = len(rms_n)

    onset_idx = int(np.argmax(rms_n > 0.05)) if np.any(rms_n > 0.05) else 0
    peak_idx = int(np.argmax(rms_n))

    attack_ms = float(t_ms[peak_idx] - t_ms[onset_idx]) if peak_idx > onset_idx else 5.0

    sus_start = min(peak_idx + max(n // 5, 1), n - 1)
    sus_end = min(n * 4 // 5, n - 1)
    sustain_level = float(np.median(rms_n[sus_start:sus_end])) if sus_start < sus_end else 0.5

    decay_ms = float(t_ms[sus_start] - t_ms[peak_idx]) if sus_start > peak_idx else 50.0

    rel_start = min(n * 4 // 5, n - 1)
    rel_seg = rms_n[rel_start:]
    if len(rel_seg) > 0 and rel_seg[0] > 0.1:
        below = np.where(rel_seg < 0.05)[0]
        rel_end = rel_start + int(below[0]) if len(below) else n - 1
        release_ms = float(t_ms[min(rel_end, n - 1)] - t_ms[rel_start])
    else:
        release_ms = 100.0

    if attack_ms < 20 and decay_ms < 300 and sustain_level < 0.3:
        env_type = 'plucked'
    elif attack_ms > 300:
        env_type = 'pad'
    elif sustain_level > 0.65:
        env_type = 'sustained'
    elif sustain_level < 0.15:
        env_type = 'percussive'
    else:
        env_type = 'standard'

    return {
        'attack_ms': round(attack_ms, 1),
        'decay_ms': round(decay_ms, 1),
        'sustain_level': round(sustain_level, 3),
        'release_ms': round(release_ms, 1),
        'type': env_type,
    }


def analyze_audio(audio_path, start_sec, end_sec):
    print("[3/4] Extracting audio features...")
    duration_arg = (end_sec - start_sec) if (start_sec is not None and end_sec is not None) else None
    y, sr = librosa.load(str(audio_path), sr=None, mono=True,
                         offset=start_sec or 0.0, duration=duration_arg)

    # --- Spectral ---
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=SPEC_HOP)[0]
    bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr, hop_length=SPEC_HOP)[0]
    rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr, hop_length=SPEC_HOP, roll_percent=0.85)[0]
    zcr = librosa.feature.zero_crossing_rate(y=y, hop_length=SPEC_HOP)[0]

    centroid_mean = float(np.mean(centroid))
    if centroid_mean < 500:
        brightness = 'dark'
    elif centroid_mean < 1500:
        brightness = 'warm'
    elif centroid_mean < 3000:
        brightness = 'mid'
    elif centroid_mean < 6000:
        brightness = 'bright'
    else:
        brightness = 'very_bright'

    # --- Harmonic / percussive ---
    y_harm, y_perc = librosa.effects.hpss(y)
    harm_e = float(np.mean(y_harm ** 2))
    perc_e = float(np.mean(y_perc ** 2))
    total_e = harm_e + perc_e + 1e-12
    harm_ratio = harm_e / total_e

    if harm_ratio > 0.8:
        harm_profile = 'highly_harmonic'
    elif harm_ratio > 0.5:
        harm_profile = 'mixed'
    else:
        harm_profile = 'noisy_or_percussive'

    # --- Pitch ---
    f0, voiced_flag, voiced_probs = librosa.pyin(
        y, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'),
        hop_length=SPEC_HOP
    )

    voiced_mask = voiced_flag if voiced_flag is not None else np.zeros(len(f0), dtype=bool)
    voiced_f0 = f0[voiced_mask] if voiced_mask.any() else np.array([])

    if len(voiced_f0) > 0:
        fundamental_hz = float(np.nanmedian(voiced_f0))
        pitch_stability = float(np.mean(voiced_probs[voiced_mask]))
        note_name = librosa.hz_to_note(fundamental_hz)
        vibrato = bool(np.nanstd(voiced_f0) / fundamental_hz > 0.02) if fundamental_hz > 0 else False
    else:
        fundamental_hz = 0.0
        pitch_stability = 0.0
        note_name = 'unpitched'
        vibrato = False

    # --- Harmonic count ---
    harmonic_count = 0
    if fundamental_hz > 20:
        D = np.abs(librosa.stft(y, hop_length=SPEC_HOP))
        freqs = librosa.fft_frequencies(sr=sr)
        global_mean = float(np.mean(D))
        for n in range(1, 16):
            target = fundamental_hz * n
            if target >= sr / 2:
                break
            idx = int(np.argmin(np.abs(freqs - target)))
            if float(np.mean(D[idx, :])) > global_mean * 1.5:
                harmonic_count += 1

    # --- LFO / modulation ---
    lfo_detected = False
    lfo_rate_hz = 0.0
    if len(centroid) > 20:
        c_diff = np.diff(centroid)
        c_fft = np.abs(np.fft.rfft(c_diff))
        c_freqs = np.fft.rfftfreq(len(c_diff), d=SPEC_HOP / sr)
        lfo_mask = (c_freqs > 0.1) & (c_freqs < 12.0)
        if np.any(lfo_mask):
            lfo_peak = float(np.max(c_fft[lfo_mask]))
            mean_p = float(np.mean(c_fft)) + 1e-12
            if lfo_peak / mean_p > 6:
                lfo_detected = True
                lfo_rate_hz = float(c_freqs[lfo_mask][np.argmax(c_fft[lfo_mask])])

    adsr = estimate_adsr(y, sr)

    return {
        'duration_seconds': round(float(librosa.get_duration(y=y, sr=sr)), 1),
        'spectral': {
            'centroid_mean_hz': round(centroid_mean, 1),
            'centroid_std_hz': round(float(np.std(centroid)), 1),
            'bandwidth_mean_hz': round(float(np.mean(bandwidth)), 1),
            'rolloff_85pct_hz': round(float(np.mean(rolloff)), 1),
            'brightness': brightness,
            'zero_crossing_rate_mean': round(float(np.mean(zcr)), 4),
        },
        'envelope': adsr,
        'pitch': {
            'fundamental_hz': round(fundamental_hz, 2),
            'note': note_name,
            'pitch_stability': round(pitch_stability, 3),
            'vibrato_detected': vibrato,
        },
        'harmonics': {
            'harmonic_ratio': round(harm_ratio, 3),
            'harmonic_count_estimate': harmonic_count,
            'harmonic_profile': harm_profile,
        },
        'modulation': {
            'lfo_detected': lfo_detected,
            'lfo_rate_hz': round(lfo_rate_hz, 2),
        },
        'percussiveness': round(perc_e / total_e, 3),
    }


def generate_spectrogram(audio_path, out_path, start_sec, end_sec):
    duration_arg = (end_sec - start_sec) if (start_sec is not None and end_sec is not None) else None
    y, sr = librosa.load(str(audio_path), sr=None, mono=True,
                         offset=start_sec or 0.0, duration=duration_arg)

    fig, axes = plt.subplots(2, 1, figsize=(14, 8))

    S_mel = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=128,
                                            fmax=8000, hop_length=SPEC_HOP)
    S_db = librosa.power_to_db(S_mel, ref=np.max)
    img = librosa.display.specshow(S_db, x_axis='time', y_axis='mel', sr=sr,
                                    fmax=8000, hop_length=SPEC_HOP, ax=axes[0])
    axes[0].set_title('Mel Spectrogram (dB)')
    fig.colorbar(img, ax=axes[0], format='%+2.0f dB')

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=SPEC_HOP)
    img2 = librosa.display.specshow(chroma, x_axis='time', y_axis='chroma',
                                     sr=sr, hop_length=SPEC_HOP, ax=axes[1])
    axes[1].set_title('Chromagram (pitch class energy over time)')
    fig.colorbar(img2, ax=axes[1])

    plt.tight_layout()
    plt.savefig(str(out_path), dpi=150, bbox_inches='tight')
    plt.close()


def main():
    parser = argparse.ArgumentParser(
        description='Analyze audio and extract features for Dirtywave M8 patch design'
    )
    parser.add_argument('url', help='SoundCloud or YouTube URL')
    parser.add_argument('description', help='Target sound, e.g. "plucked lead synth in chorus"')
    parser.add_argument('--start', default=None, help='Analysis start time (MM:SS or seconds)')
    parser.add_argument('--end', default=None, help='Analysis end time (MM:SS or seconds)')
    parser.add_argument('--stem', default='other',
                        choices=['other', 'vocals', 'bass', 'drums', 'full'],
                        help='Demucs stem to analyze (default: other)')
    args = parser.parse_args()

    start_sec = parse_time(args.start) if args.start else None
    end_sec = parse_time(args.end) if args.end else None

    output_root = Path('output')
    workspace = output_root / '_workspace'
    workspace.mkdir(parents=True, exist_ok=True)

    # Download
    dl_dir = workspace / 'downloads'
    dl_dir.mkdir(exist_ok=True)
    wav_path = download_audio(args.url, dl_dir)

    track_slug = safe_slug(wav_path.stem)
    track_out = output_root / track_slug
    track_out.mkdir(parents=True, exist_ok=True)

    # Stem separation
    if args.stem == 'full':
        analysis_audio = wav_path
        stem_label = 'full_mix'
    else:
        stems_dir = workspace / 'stems'
        stems_dir.mkdir(exist_ok=True)
        stems = separate_stems(wav_path, stems_dir)

        target = args.stem
        if target not in stems:
            print(f"Warning: '{target}' stem not found, falling back to 'other'")
            target = 'other'
        if target not in stems:
            sys.exit("No usable stem found.")
        analysis_audio = stems[target]
        stem_label = target

    # Analysis
    features = analyze_audio(analysis_audio, start_sec, end_sec)

    # Spectrogram
    print("[4/4] Generating spectrogram...")
    spec_path = track_out / 'spectrogram.png'
    generate_spectrogram(analysis_audio, spec_path, start_sec, end_sec)

    # Write JSON
    result = {
        'track': {
            'title': wav_path.stem,
            'url': args.url,
            'target_sound_description': args.description,
            'stem_analyzed': stem_label,
            'time_range': {'start_seconds': start_sec, 'end_seconds': end_sec},
        },
        'analysis': features,
        'output_files': {
            'spectrogram_png': str(spec_path),
            'stem_audio_wav': str(analysis_audio),
        },
    }

    json_path = track_out / 'analysis.json'
    json_path.write_text(json.dumps(result, indent=2))

    print(f"\nDone.")
    print(f"  JSON:        {json_path}")
    print(f"  Spectrogram: {spec_path}")
    print(f"\nTo get M8 patch recommendations:")
    print(f"  1. Open a new Claude Code session in this project folder")
    print(f"  2. Paste the contents of {json_path}")
    print(f"  3. Attach {spec_path} as an image")
    print(f'  4. Ask: "Recommend an M8 patch to imitate: {args.description}"')


if __name__ == '__main__':
    main()
