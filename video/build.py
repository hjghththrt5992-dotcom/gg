#!/usr/bin/env python3
"""Build 《光标先生的自我介绍》.

    python build.py                # full build -> out/claude_intro.mp4
    python build.py --stills 4     # only dump a few preview frames -> out/stills/
    python build.py --audio-only   # only synthesize the soundtrack -> out/audio.wav
"""
import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

import audio
from script import FPS, build

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
W, H = 1080, 1920
MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-melo-tts-zh_en.tar.bz2"


def ensure_model():
    if (audio.MODEL_DIR / "model.onnx").exists():
        return
    print("downloading TTS model (~160 MB)…", flush=True)
    audio.MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
    tgz = audio.MODEL_DIR.parent / "melo.tar.bz2"
    urllib.request.urlretrieve(MODEL_URL, tgz)
    with tarfile.open(tgz) as t:
        t.extractall(audio.MODEL_DIR.parent)
    tgz.unlink()


def ffmpeg():
    import imageio_ffmpeg
    return shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stills", type=int, default=0, help="render N evenly spaced preview frames only")
    ap.add_argument("--at", type=float, nargs="*", help="render stills at these timestamps (seconds)")
    ap.add_argument("--audio-only", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    ensure_model()

    s = build()
    b, duration = s["board"], s["duration"]
    n_frames = int(duration * FPS) + 1
    print(f"duration {duration:.2f}s, {n_frames} frames, {len(b.voice)} voice clips, {len(b.sfx)} sfx", flush=True)

    mixed, voice_only = audio.mix(duration, b.voice, b.sfx)
    sf.write(OUT / "audio.wav", mixed, audio.SR)
    if args.audio_only:
        return

    tl = dict(fps=FPS, width=W, height=H, duration=duration, events=b.ev, subs=b.subs,
              amp=[round(float(v), 3) for v in audio.mouth_envelope(voice_only, FPS, n_frames + 1)])
    (OUT / "timeline.json").write_text(json.dumps(tl, ensure_ascii=False))

    import render
    if args.stills or args.at:
        d = OUT / "stills"
        shutil.rmtree(d, ignore_errors=True)
        ts = args.at if args.at else list(np.linspace(0.5, duration - 0.5, args.stills))
        frames = [int(t * FPS) for t in ts]
        render.render_frames(tl, d, workers=min(args.workers, len(frames)), only=frames)
        print("stills:", ", ".join(f"{f / FPS:.1f}s" for f in frames), "->", d)
        return

    fdir = HERE / ".cache" / "frames"
    shutil.rmtree(fdir, ignore_errors=True)
    print("rendering frames…", flush=True)
    render.render_frames(tl, fdir, workers=args.workers)

    mp4 = OUT / "claude_intro.mp4"
    cmd = [
        ffmpeg(), "-y", "-loglevel", "error",
        "-framerate", str(FPS), "-i", str(fdir / "%05d.png"), "-i", str(OUT / "audio.wav"),
        "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        "-c:v", "libx264", "-preset", "slow", "-crf", "19",
        "-af", "loudnorm=I=-15:TP=-1.5:LRA=9",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        "-t", f"{duration:.3f}", "-movflags", "+faststart", str(mp4),
    ]
    subprocess.run(cmd, check=True)
    print("done ->", mp4, f"({mp4.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    sys.exit(main())
