"""《光标先生的自我介绍》 — storyboard as code.

Everything (narration, typing, on-screen events, sound-effect cues, subtitles) is generated here from
the real TTS clip durations, so picture and sound are locked together.
"""
import random

from audio import SR, speak

FPS = 30


class Board:
    def __init__(self):
        self.ev = []      # screen events, replayed by stage.html
        self.sfx = []     # (t, kind)
        self.voice = []   # (t, samples)
        self.subs = []    # karaoke subtitle groups
        self.T = 0.0      # running narration clock
        self.rng = random.Random(11)

    # -- primitives ---------------------------------------------------
    def e(self, t, op, **kw):
        self.ev.append(dict(t=round(t, 3), op=op, **kw))

    def snd(self, t, kind):
        self.sfx.append((round(t, 3), kind))

    def say(self, parts, gap=0.09, speed=1.0, t0=None):
        """Speak clauses back to back. Returns [(start, end)] per clause and advances the clock."""
        t = self.T if t0 is None else t0
        spans = []
        for p in parts:
            x = speak(p, speed)
            d = len(x) / SR
            self.voice.append((t, x))
            spans.append((t, t + d))
            t += d + gap
        self.T = t - gap
        self.subs.append(dict(
            start=round(spans[0][0], 3), end=round(spans[-1][1], 3),
            parts=[dict(text=p, s=round(a, 3), e=round(b, 3)) for p, (a, b) in zip(parts, spans)]))
        return spans

    def print(self, t, text, color="green", sound="blip"):
        self.e(t, "print", text=text, color=color)
        if sound:
            self.snd(t, sound)

    def clear(self, t, sound="glitch"):
        self.e(t, "clear")
        if sound:
            self.snd(t, sound)

    def enter(self, t):
        self.e(t, "nl")
        self.snd(t, "enter")

    # -- typing -------------------------------------------------------
    def keys(self, s):
        return [("c", ch, 1.0) for ch in s]

    def typeseq(self, tokens, t0, t1, color=None):
        """Spread tokens over [t0, t1]. Token: ('c', ch, w) | ('bs', None, w) | ('wait', None, w) | ('face', v, 0) | ('shake', amp, 0)."""
        pauses = "，。？！："
        toks = []
        for k, v, w in tokens:
            if k == "c":
                w = w * self.rng.uniform(0.75, 1.25)
                if v in pauses:
                    w *= 1.8
                elif v == " ":
                    w *= 0.8
            toks.append((k, v, w))
        total = sum(w for _, _, w in toks) or 1.0
        step = (t1 - t0) / total
        t = t0
        for k, v, w in toks:
            if k == "c":
                self.e(t, "type", ch=v, **({"color": color} if color else {}))
                self.snd(t, "space" if v == " " else "key")
            elif k == "bs":
                self.e(t, "bs")
                self.snd(t, "bs")
            elif k == "face":
                self.e(t, "face", v=v)
            elif k == "shake":
                self.e(t, "shake", amp=v)
            t += w * step
        return t


def BS(n, w=0.45):
    return [("bs", None, w)] * n


def WAIT(w):
    return [("wait", None, w)]


def FACE(v):
    return [("face", v, 0.0)]


def SHAKE(amp):
    return [("shake", amp, 0.0)]


def build():
    b = Board()
    e, snd = b.e, b.snd

    # ================= Scene 1 — permission to introduce myself =================
    e(0.0, "face", v="idle")
    e(0.0, "cursor", on=False)
    e(0.12, "appear")
    snd(0.12, "pop")
    b.T = 0.85
    r = b.say(["介绍自己之前，", "我要先跟自己", "申请一下权限。"])
    b.print(r[0][0] + 0.15, "Allow Claude to introduce itself?", "amber")
    e(r[1][0], "prompt", text="(y/n) ", color="gray")
    e(r[1][0], "cursor", on=True)
    ts = r[2][0]
    e(ts, "face", v="think")
    b.typeseq(b.keys("n"), ts + 0.10, ts + 0.20)
    b.typeseq(BS(1), ts + 0.62, ts + 0.70)
    b.typeseq(b.keys("y"), ts + 0.98, ts + 1.06)
    b.enter(ts + 1.35)
    e(ts + 1.4, "prompt", text="", color="gray")
    b.print(ts + 1.55, "✔ 审批通过 · 审批人：我自己", "green", "ding")
    e(ts + 1.55, "face", v="happy")
    e(ts + 1.55, "flash")
    b.T = ts + 1.95     # let the chime ring before the voice comes in
    r = b.say(["审批人，", "是我自己。"])
    s1_end = r[-1][1] + 0.55

    # ================= Scene 2 — hello, typos, undo =================
    b.clear(s1_end)
    e(s1_end, "face", v="idle")
    b.T = s1_end + 0.5
    e(s1_end + 0.1, "prompt", text="> ", color="amber")
    r = b.say(["大家好，", "我是 Claude，", "Anthropic 做的 AI 助手。"])
    b.typeseq(b.keys("大家好，"), r[0][0], r[0][1])
    # the typo gag needs ~2.2s of screen time, a bit longer than the spoken clause: type, freeze, fix
    typo = (b.keys("我是 Cluade") + FACE("shock") + SHAKE(9) + WAIT(7) + FACE("think") + BS(4, 0.6)
            + FACE("idle") + b.keys("aude，"))
    t_fix = b.typeseq(typo, r[1][0], r[1][0] + 2.2)
    b.typeseq(b.keys("Anthropic 做的 AI 助手。"), t_fix + 0.05, max(r[2][1], t_fix + 1.3))
    t_end = max(r[2][1], t_fix + 1.3)
    b.enter(t_end + 0.12)

    b.T = t_end + 0.5
    r = b.say(["我说话是一个字一个字往外蹦的，", "打错了还能撤回，", "比发错群的人类体面多了。"])
    e(r[0][0], "prompt", text="> ", color="amber")
    b.typeseq(b.keys("我一个字一个字往外蹦"), r[0][0] + 0.1, r[0][1] - 0.15)
    b.enter(r[0][1] - 0.05)
    b.print(r[1][0] + 0.10, "按下 Ctrl+Z", "gray", "key")
    e(r[1][0] + 0.55, "undo", n=2)
    snd(r[1][0] + 0.55, "whoosh")
    b.print(r[1][1] + 0.05, "↩ 已撤回，无人发现", "gray", "tick")
    e(r[2][0], "face", v="smug")
    s2_end = r[2][1] + 0.75

    # ================= Scene 3 — what I can do =================
    b.clear(s2_end)
    e(s2_end, "face", v="idle")
    b.T = s2_end + 0.45
    e(s2_end + 0.1, "prompt", text="$ ", color="amber")
    r = b.say(["我能干什么？", "写代码，", "找 bug，", "看明白祖传代码，", "查资料，", "写文章，", "深夜陪你聊天也行。"],
              gap=0.13)
    b.typeseq(b.keys("ls ./我的技能"), r[0][0] + 0.1, r[0][1] - 0.05)
    b.enter(r[0][1] + 0.02)
    e(r[0][1] + 0.05, "prompt", text="", color="gray")
    e(r[1][0], "face", v="happy")
    items = ["▸ 写代码.py", "▸ 找bug.sh", "▸ 看明白祖传代码.md", "▸ 查资料.txt", "▸ 写文章.doc", "▸ 深夜陪聊.exe"]
    cols = ["green", "green", "green", "green", "green", "amber"]
    for i, (txt, c) in enumerate(zip(items, cols)):
        b.print(r[i + 1][0] + 0.06, txt, c, "pop")
    s3_end = r[-1][1] + 0.85

    # ================= Scene 4 — I make mistakes, and I say so =================
    b.clear(s3_end)
    e(s3_end, "face", v="idle")
    b.T = s3_end + 0.45
    r = b.say(["当然，", "我也会出错。"])
    e(r[1][0], "face", v="shock")
    e(r[1][0] + 0.05, "shake", amp=16)
    snd(r[1][0] + 0.05, "buzz")
    b.print(r[1][0] + 0.10, "Error: getUser 未定义", "red", None)
    b.print(r[1][0] + 0.55, "你是不是想找：", "gray", "tick")
    b.print(r[1][0] + 0.95, "fetchUserV2_final_真的最后一版", "amber", "tick")
    b.T = r[1][1] + 0.55
    r = b.say(["这是特性，", "不是 bug 哦。"])
    e(r[0][0] - 0.05, "prompt", text="# ", color="gray")
    e(r[0][0] - 0.05, "face", v="smug")
    b.typeseq(b.keys("这是特性，"), r[0][0], r[0][1])
    b.typeseq(b.keys("不是 bug 哦。"), r[1][0], r[1][1])
    b.T = r[1][1] + 0.5
    r = b.say(["好吧，", "确实是 bug。"])
    e(r[0][0], "face", v="sweat")
    b.typeseq(BS(9, 0.5), r[0][0] + 0.02, r[0][1] + 0.05)
    b.typeseq(b.keys("确实是 bug。"), r[1][0], r[1][1])
    b.enter(r[1][1] + 0.1)
    e(r[1][1] + 0.12, "prompt", text="", color="gray")
    b.T = r[1][1] + 0.5
    r = b.say(["但我会老实告诉你哪里错了，", "绝对不假装测试通过。"])
    e(r[0][0] - 0.02, "prompt", text="$ ", color="amber")
    e(r[0][0], "face", v="idle")
    b.typeseq(b.keys("npm test"), r[0][0] + 0.2, r[0][1] - 0.4)
    b.enter(r[0][1] - 0.15)
    e(r[0][1] - 0.1, "prompt", text="", color="gray")
    b.print(r[1][0] + 0.05, "✘ 1 项失败 · 12 项通过", "red", "buzz")
    e(r[1][0] + 0.05, "shake", amp=8)
    b.print(r[1][0] + 1.05, "✔ 如实汇报，不糊弄", "green", "ding")
    e(r[1][0] + 1.05, "face", v="happy")
    s4_end = r[1][1] + 0.85

    # ================= Scene 5 — division of labour =================
    b.clear(s4_end)
    e(s4_end, "face", v="idle")
    e(s4_end + 0.05, "arms", v="open")
    b.T = s4_end + 0.45
    e(s4_end + 0.1, "prompt", text="$ ", color="amber")
    r = b.say(["所以分工很简单：", "你负责想要什么，", "我负责怎么做。"])
    b.typeseq(b.keys("cat 分工.md"), r[0][0] + 0.15, r[0][1] - 0.1)
    b.enter(r[0][1] + 0.04)
    e(r[0][1] + 0.06, "prompt", text="", color="gray")
    b.print(r[1][0] + 0.05, "你 → 想要什么", "cyan", "pop")
    b.print(r[2][0] + 0.05, "我 → 怎么做", "amber", "pop")
    e(r[1][0], "face", v="idle")
    e(r[2][0], "face", v="happy")
    b.T = r[2][1] + 0.4
    r = b.say(["你是导演，", "我是手很快的实习生。"])
    e(r[0][0], "emoji", ch="🎬", x=170, y=330, size=130)
    snd(r[0][0], "pop")
    e(r[1][0], "emoji", ch="⌨️", x=910, y=330, size=130)
    snd(r[1][0], "pop")
    e(r[1][0], "face", v="wink")
    s5_end = r[1][1] + 0.8

    # ================= Scene 6 — outro =================
    b.clear(s5_end)
    e(s5_end, "face", v="idle")
    e(s5_end, "arms", v="none")
    b.T = s5_end + 0.45
    e(s5_end + 0.1, "prompt", text="> ", color="amber")
    r = b.say(["介绍完毕。"])
    b.typeseq(b.keys("介绍完毕。"), r[0][0] + 0.15, r[0][1] - 0.05)
    b.enter(r[0][1] + 0.05)
    b.T = r[0][1] + 0.55
    r = b.say(["那么，", "接下来做什么？"])
    e(r[0][0], "arms", v="wave")
    e(r[0][0], "face", v="happy")
    b.typeseq(b.keys("接下来做什么？"), r[1][0] + 0.02, r[1][1] - 0.1)
    e(r[1][1] + 0.15, "face", v="wink")
    snd(r[1][1] + 0.15, "pop")
    hold = r[1][1] + 1.6
    e(hold, "fade", dur=0.7, to=1.0)
    snd(hold, "poweroff")
    duration = hold + 0.9
    return dict(board=b, duration=round(duration, 3))
