"""Audio for the intro video: offline Chinese TTS, synthesized SFX, chiptune bed, mixdown."""
import hashlib
import os
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100
HERE = Path(__file__).resolve().parent
CACHE = HERE / ".cache" / "tts"
MODEL_DIR = Path(os.environ.get("TTS_MODEL_DIR", HERE / ".cache" / "models" / "vits-melo-tts-zh_en"))

_tts = {}
# 0 = deterministic: same text -> same audio on every build (default VITS noise makes takes differ run to run)
NOISE = (float(os.environ.get("TTS_NOISE", 0.0)), float(os.environ.get("TTS_NOISE_W", 0.0)))

# Words the stock lexicon lacks. Format: word, ARPAbet-style phones, then one tone id per phone
# (7 = consonant, 8 = unstressed vowel, 9 = primary stress, 10 = secondary stress — copied from
# "anthropology" / "topic" in the same file).
LEXICON_PATCH = {
    "anthropic": "ae n th r aa p ih k 9 7 7 7 10 7 8 7",
}


def _patch_lexicon():
    path = MODEL_DIR / "lexicon.txt"
    lines = path.read_text(encoding="utf-8").splitlines()
    keep = [ln for ln in lines if ln and ln.split(" ", 1)[0] not in LEXICON_PATCH]
    keep += [f"{w} {ph}" for w, ph in LEXICON_PATCH.items()]
    text = "\n".join(keep) + "\n"
    if text != path.read_text(encoding="utf-8"):
        path.write_text(text, encoding="utf-8")


def _engine(noise=None):
    noise = noise or NOISE
    if noise not in _tts:
        import sherpa_onnx

        _patch_lexicon()

        d = str(MODEL_DIR)
        cfg = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=f"{d}/model.onnx",
                    lexicon=f"{d}/lexicon.txt",
                    tokens=f"{d}/tokens.txt",
                    dict_dir=f"{d}/dict",
                    noise_scale=noise[0],
                    noise_scale_w=noise[1],
                ),
                num_threads=4,
                provider="cpu",
            ),
            rule_fsts=f"{d}/date.fst,{d}/number.fst,{d}/phone.fst,{d}/new_heteronym.fst",
            max_num_sentences=1,
        )
        _tts[noise] = sherpa_onnx.OfflineTts(cfg)
    return _tts[noise]


def _trim(x, pad=0.06, thresh=0.004):
    peak = np.abs(x).max()
    idx = np.where(np.abs(x) > thresh * peak)[0]
    if len(idx) == 0:
        return x
    a = max(0, idx[0] - int(pad * SR))
    b = min(len(x), idx[-1] + int(pad * SR))
    return x[a:b]


def speak(text, speed=1.0):
    """Synthesize one clip (cached). Returns mono float32 at SR, edges trimmed."""
    key = hashlib.sha1(f"{text}|{speed}|melo|{sorted(LEXICON_PATCH.items())}".encode()).hexdigest()[:16]
    p = CACHE / f"{key}.wav"
    if not p.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        a = _engine().generate(text, sid=0, speed=speed)
        assert a.sample_rate == SR, a.sample_rate
        x = _trim(np.asarray(a.samples, dtype=np.float32))
        x = x / (np.abs(x).max() + 1e-9) * 0.9
        sf.write(p, x, SR)
    x, sr = sf.read(p, dtype="float32")
    assert sr == SR
    return x


# ---------------------------------------------------------------- SFX

def _env(n, tau):
    return np.exp(-np.arange(n) / (SR * tau))


def _sine(freq, n, phase=0.0):
    return np.sin(2 * np.pi * freq * np.arange(n) / SR + phase)


def _hp(x, k=0.9):
    """one-pole-ish high-pass via first difference blend"""
    y = np.empty_like(x)
    y[0] = x[0]
    y[1:] = x[1:] - k * x[:-1]
    return y


def make_sfx(kind, rng):
    if kind == "key":
        n = int(0.06 * SR)
        noise = _hp(rng.standard_normal(n)) * _env(n, 0.0025)
        body = _sine(rng.uniform(150, 230), n) * _env(n, 0.012) * 0.6
        return (noise * 0.55 + body) * 0.9
    if kind == "space":
        n = int(0.09 * SR)
        noise = _hp(rng.standard_normal(n), 0.7) * _env(n, 0.004)
        body = _sine(rng.uniform(95, 125), n) * _env(n, 0.03) * 0.9
        return noise * 0.5 + body
    if kind == "bs":
        n = int(0.05 * SR)
        noise = _hp(rng.standard_normal(n)) * _env(n, 0.002)
        body = _sine(rng.uniform(260, 320), n) * _env(n, 0.008)
        return noise * 0.45 + body * 0.5
    if kind == "enter":
        n = int(0.16 * SR)
        noise = _hp(rng.standard_normal(n), 0.8) * _env(n, 0.006)
        body = _sine(85, n) * _env(n, 0.05)
        return noise * 0.5 + body * 1.0
    if kind == "ding":
        n = int(0.7 * SR)
        a = _sine(988, n) * _env(n, 0.16)
        b = np.zeros(n)
        off = int(0.11 * SR)
        b[off:] = (_sine(1318, n - off) + 0.4 * _sine(2636, n - off)) * _env(n - off, 0.22)
        return (a * 0.7 + b) * 0.55
    if kind == "buzz":
        n = int(0.32 * SR)
        t = np.arange(n) / SR
        sq = np.sign(np.sin(2 * np.pi * 110 * t)) + 0.6 * np.sign(np.sin(2 * np.pi * 116 * t))
        k = np.ones(6) / 6
        sq = np.convolve(sq, k, mode="same")
        return sq * np.minimum(1, _env(n, 0.16) * 1.3) * 0.32
    if kind == "pop":
        n = int(0.11 * SR)
        f = np.linspace(380, 880, n)
        ph = 2 * np.pi * np.cumsum(f) / SR
        return np.sin(ph) * _env(n, 0.03) * 0.55
    if kind == "blip":
        n = int(0.06 * SR)
        f = 720
        tri = 2 * np.abs(2 * ((f * np.arange(n) / SR) % 1) - 1) - 1
        return tri * _env(n, 0.02) * 0.4
    if kind == "glitch":
        n = int(0.2 * SR)
        noise = rng.standard_normal(n)
        step = 24
        held = np.repeat(noise[::step], step)[:n]  # sample & hold = crushed noise
        gate = (np.sin(np.arange(n) / SR * 2 * np.pi * 38) > -0.2).astype(float)
        return held * gate * _env(n, 0.09) * 0.35
    if kind == "whoosh":
        n = int(0.28 * SR)
        noise = rng.standard_normal(n)
        k = np.ones(40) / 40
        sm = np.convolve(noise, k, mode="same")
        env = np.sin(np.linspace(0, np.pi, n)) ** 2
        return sm * env * 1.6
    if kind == "poweroff":
        n = int(0.5 * SR)
        f = np.linspace(900, 55, n) ** 1.0
        ph = 2 * np.pi * np.cumsum(f) / SR
        return np.sin(ph) * _env(n, 0.2) * 0.5
    if kind == "tick":
        n = int(0.03 * SR)
        return _hp(rng.standard_normal(n)) * _env(n, 0.0015) * 0.35
    raise ValueError(kind)


SFX_GAIN = {"key": 0.5, "space": 0.5, "bs": 0.5, "enter": 0.7, "ding": 0.6, "buzz": 0.55,
            "pop": 0.6, "blip": 0.5, "glitch": 0.6, "whoosh": 0.5, "poweroff": 0.6, "tick": 0.5}


# ---------------------------------------------------------------- music

def _note(freq, dur, kind="pulse", duty=0.25):
    n = int(dur * SR)
    t = np.arange(n) / SR
    ph = (freq * t) % 1.0
    if kind == "pulse":
        w = np.where(ph < duty, 1.0, -1.0)
    else:  # triangle
        w = 4 * np.abs(ph - 0.5) - 1
    return w


def make_music(duration, bpm=104):
    """Quiet 8-bit bed: Am - F - C - G, arpeggio + triangle bass. Only chord tones, so nothing clashes."""
    beat = 60.0 / bpm
    eighth = beat / 2
    hz = lambda m: 440.0 * 2 ** ((m - 69) / 12)
    # (bass root midi, chord tones midi)
    prog = [(45, [57, 60, 64]), (41, [53, 57, 60]), (48, [55, 60, 64]), (43, [55, 59, 62])]
    out = np.zeros(int((duration + 2) * SR), dtype=np.float32)
    bar = 0
    t = 0.0
    pattern = [0, 1, 2, 1, 0, 1, 2, 1]
    while t < duration:
        root, tones = prog[bar % 4]
        # bass on beats 1 and 3
        for k in (0, 2):
            tb = t + k * beat
            b = _note(hz(root), beat * 1.6, "tri") * _env(int(beat * 1.6 * SR), 0.45) * 0.55
            i = int(tb * SR)
            if i + len(b) < len(out):
                out[i:i + len(b)] += b
        for j, p in enumerate(pattern):
            tn = t + j * eighth
            note = _note(hz(tones[p] + 12), eighth * 1.8) * _env(int(eighth * 1.8 * SR), 0.11) * 0.28
            i = int(tn * SR)
            if i + len(note) < len(out):
                out[i:i + len(note)] += note
        t += 4 * beat
        bar += 1
    out = out[: int(duration * SR)]
    fade = np.ones_like(out)
    fi, fo = int(1.2 * SR), int(1.8 * SR)
    fade[:fi] = np.linspace(0, 1, fi)
    fade[-fo:] = np.linspace(1, 0, fo)
    return out * fade


# ---------------------------------------------------------------- mix

def mix(duration, voice, sfx, music_gain=0.11, sfx_gain=0.42, seed=7):
    """voice: [(t, mono)], sfx: [(t, kind)]. Returns (mix, voice_only) mono float32."""
    n = int(duration * SR)
    v = np.zeros(n, dtype=np.float32)
    for t, x in voice:
        i = int(t * SR)
        m = min(len(x), n - i)
        v[i:i + m] += x[:m]
    rng = np.random.default_rng(seed)
    s = np.zeros(n + SR, dtype=np.float32)
    for t, kind in sfx:
        x = make_sfx(kind, rng).astype(np.float32) * SFX_GAIN[kind]
        i = int(t * SR)
        if i < 0 or i >= n:
            continue
        m = min(len(x), len(s) - i)
        s[i:i + m] += x[:m]
    s = s[:n]
    music = make_music(duration)
    # sidechain-style ducking: music and SFX both get out of the voice's way
    win = int(0.12 * SR)
    env = np.convolve(np.abs(v), np.ones(win) / win, mode="same")
    level = np.clip(env / 0.12, 0, 1)
    music = music * (1.0 - 0.55 * level)
    s = s * (1.0 - 0.5 * level)
    m = v + sfx_gain * s + music_gain * music
    peak = np.abs(m).max()
    if peak > 0.97:
        m = m / peak * 0.97
    return m.astype(np.float32), v


def mouth_envelope(voice_only, fps, n_frames):
    """Per-frame 0..1 loudness of the voice, for lip-sync."""
    hop = SR / fps
    rms = np.zeros(n_frames)
    for f in range(n_frames):
        a = int(f * hop)
        b = int((f + 1) * hop)
        seg = voice_only[a:b]
        rms[f] = np.sqrt(np.mean(seg ** 2)) if len(seg) else 0.0
    ref = np.percentile(rms[rms > 0.005], 90) if (rms > 0.005).any() else 1.0
    env = np.clip(rms / ref, 0, 1)
    # light smoothing so the mouth doesn't flutter
    sm = env.copy()
    for i in range(1, len(sm)):
        sm[i] = 0.55 * env[i] + 0.45 * sm[i - 1]
    return sm
