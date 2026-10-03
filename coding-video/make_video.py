#!/usr/bin/env python3
"""生成「看 Claude 写代码」演示视频（1920x1080，30fps，H.264 MP4）。

视频演示一个完整的小任务：比较两个内核版本号的大小。
画面里的 grep 结果、代码、pytest 输出和 git 提交都是真实的：脚本先在临时目录里
把代码写出来、跑测试、修 bug、再跑测试、提交，再把这些真实结果逐帧画成视频。
打字动画是为了看清楚而放慢的，实际写文件是一次写入。

依赖：
  Python 3.9+，pip install pillow pygments pytest
  ffmpeg（带 libx264）
  字体 DejaVu Sans Mono、文泉驿正黑（Debian/Ubuntu：fonts-dejavu-core fonts-wqy-zenhei）

用法：
  python3 make_video.py                     # 输出 claude-coding-process.mp4
  python3 make_video.py out.mp4             # 指定输出路径
  python3 make_video.py --preview DIR       # 不编码，每秒存一帧 PNG 到 DIR，调画面用
"""
import os
import random
import re
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pygments.lexers import PythonLexer
from pygments.token import Token

HERE = Path(__file__).resolve().parent
BUILD_SH = HERE.parent / "oneplus-pad-pro-kernel" / "build.sh"

W, H, FPS = 1920, 1080, 30

# ---------------------------------------------------------------- 剧本里的代码

PROMPT = "帮我写个函数，比较两个内核版本号的大小，比如 6.1.118 和 6.1.75"

KVER_BUGGY = '''\
def parse(version):
    """'6.1.118-android14-11' -> 拆成 6、1、118 三段"""
    core = version.split("-")[0]
    return core.split(".")


def compare(a, b):
    """a > b 返回 1，相等返回 0，a < b 返回 -1"""
    pa, pb = parse(a), parse(b)
    if pa > pb:
        return 1
    if pa < pb:
        return -1
    return 0
'''

BUG_EXPR = 'core.split(".")'
FIX_PREFIX, FIX_SUFFIX = "[int(x) for x in ", "]"
BUG_LINE = '    return ' + BUG_EXPR
FIX_LINE = '    return ' + FIX_PREFIX + BUG_EXPR + FIX_SUFFIX
KVER_FIXED = KVER_BUGGY.replace(BUG_LINE, FIX_LINE)

TEST_KVER = '''\
from kver import compare


def test_equal():
    assert compare("6.1.75", "6.1.75") == 0


def test_patch_level():
    assert compare("6.1.118", "6.1.75") == 1


def test_suffix_ignored():
    assert compare("6.1.118-android14-11", "6.1.118") == 0


def test_major():
    assert compare("5.15.0", "6.1.0") == -1
'''
FAIL_ASSERT = 'compare("6.1.118", "6.1.75")'

GREP_PATTERN = "kernelversion|LOCALVERSION_STR="
PYTEST_CMD = "python3 -m pytest -q --tb=short"
COMMIT_MSG = "Add kernel version compare helper"


def line_no(text, needle):
    """needle 所在的行号（从 1 开始）。"""
    return text[:text.index(needle)].count("\n") + 1


def run_for_real():
    """真实执行一遍：grep、写代码、跑测试、修复、再跑、提交。返回每一步的输出行。"""
    if not BUILD_SH.is_file():
        sys.exit(f"找不到 {BUILD_SH}，请在仓库里运行本脚本")
    grep = subprocess.run(["grep", "-nE", GREP_PATTERN, str(BUILD_SH)],
                          capture_output=True, text=True, check=True).stdout

    # COLUMNS 让 pytest 的分隔线正好放进视频里终端的宽度
    env = dict(os.environ, COLUMNS="50", PYTHONDONTWRITEBYTECODE="1")
    git = ["git", "-c", "user.name=Claude", "-c", "user.email=noreply@anthropic.com",
           "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)

        def sh(*cmd):
            return subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True)

        def pytest():
            return sh(sys.executable, "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider")

        sh(*git, "init", "-q", "-b", "main")
        sh(*git, "commit", "-q", "--allow-empty", "-m", "Initial commit")
        (work / "kver.py").write_text(KVER_BUGGY)
        (work / "test_kver.py").write_text(TEST_KVER)
        failed = pytest()
        (work / "kver.py").write_text(KVER_FIXED)
        passed = pytest()
        sh(*git, "add", "kver.py", "test_kver.py")
        commit = sh(*git, "commit", "-m", COMMIT_MSG)

    if failed.returncode != 1 or passed.returncode != 0 or commit.returncode != 0:
        sys.exit("真实运行的结果和剧本对不上：\n" + failed.stdout + passed.stdout
                 + commit.stdout + commit.stderr)

    def clean(out):
        return [ln.rstrip() for ln in out.splitlines() if ln.strip()]

    return {
        "grep": clean(grep),
        "failed": clean(failed.stdout),
        "passed": clean(passed.stdout),
        "commit": clean(commit.stdout)[:2],
    }


# ---------------------------------------------------------------- 外观

BG = (12, 14, 20)
PANEL = (22, 25, 33)
CHROME = (31, 35, 45)
TABBAR = (18, 21, 28)
BORDER = (46, 51, 64)
FG = (222, 225, 230)
DIM = (128, 136, 152)
FAINT = (78, 85, 100)
ORANGE = (217, 119, 87)
ORANGE_SOFT = (232, 160, 132)
GREEN = (115, 201, 145)
RED = (240, 113, 120)
LINE_HL = (29, 33, 43)
SEL = (40, 78, 118)
RED_BG = (78, 32, 40)
GREEN_BG = (28, 66, 44)
YELLOW_BG = (72, 60, 26)

SYN = {
    "keyword": (198, 120, 221),
    "func": (97, 175, 239),
    "string": (152, 195, 121),
    "number": (209, 154, 102),
    "builtin": (229, 192, 123),
    "op": (86, 182, 194),
    "name": (224, 108, 117),
    "punct": (171, 178, 191),
    "comment": (110, 118, 135),
}

EDITOR = (40, 104, 1110, 904)
TERM = (1140, 104, 1880, 904)
CHROME_H = 44
TAB_H = 46
GUTTER = 84
C_SIZE, C_LH = 25, 35          # 编辑器字号、行高
T_SIZE, T_LH = 21, 31          # 终端字号、行高
CAP_SIZE = 36
SPIN = "·✢✳✶✻✽✻✶✳✢"

FONT_FILES = {
    "mono": ("DejaVu Sans Mono", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
    "bold": ("DejaVu Sans Mono:bold", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"),
    "cjk": (":lang=zh-cn", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
}


@lru_cache(None)
def font(kind, size):
    name, path = FONT_FILES[kind]
    if not Path(path).is_file():
        path = subprocess.run(["fc-match", "-f", "%{file}", name],
                              capture_output=True, text=True).stdout.strip()
    return ImageFont.truetype(path, size)


def font_kind(ch, style, bold):
    """mono：西文用 DejaVu Sans Mono，中文用文泉驿；sans：除了 ✻✓ 这类符号都用文泉驿。"""
    o = ord(ch)
    if style == "sans":
        return "bold" if 0x2700 <= o <= 0x27BF else "cjk"
    if o >= 0x2E80 or 0x2460 <= o <= 0x24FF:
        return "cjk"
    return "bold" if bold else "mono"


@lru_cache(None)
def char_w(ch, kind, size):
    return font(kind, size).getlength(ch)


def text_w(text, size, style="mono", bold=False):
    return sum(char_w(ch, font_kind(ch, style, bold), size) for ch in text)


def draw_text(d, x, y, text, color, size, style="mono", bold=False, stroke=0):
    """从 (x, 基线 y) 开始画中英混排文本，返回结束处的 x。"""
    run, kind = "", None
    for ch in text + "\0":
        k = font_kind(ch, style, bold) if ch != "\0" else None
        if k != kind and run:
            d.text((x, y), run, font=font(kind, size), fill=color, anchor="ls",
                   stroke_width=stroke, stroke_fill=color)
            x += sum(char_w(c, kind, size) for c in run)
            run = ""
        run, kind = run + ch, k
    return x


def draw_center(d, cx, y, text, color, size, style="sans", stroke=0):
    draw_text(d, cx - text_w(text, size, style) / 2, y, text, color, size, style, stroke=stroke)


def draw_chip(d, x, y, label, state, size=21):
    """步骤标签。state：current / done / todo。返回宽度。"""
    w = text_w(label, size, "sans") + 2 * size
    h = size * 2
    fill, outline, color = {
        "current": (ORANGE, ORANGE, (24, 18, 16)),
        "done": ((26, 44, 34), (52, 98, 70), GREEN),
        "todo": (BG, BORDER, FAINT),
    }[state]
    d.rounded_rectangle([x, y, x + w, y + h], h // 2, fill=fill, outline=outline, width=2)
    draw_text(d, x + size, y + h / 2 + size * 0.36, label, color, size, "sans")
    return w


def draw_window(d, box, title):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, 12, fill=PANEL, outline=BORDER, width=2)
    d.rounded_rectangle([x0, y0, x1, y0 + CHROME_H + 12], 12, fill=CHROME, outline=BORDER, width=2)
    d.rectangle([x0 + 2, y0 + CHROME_H, x1 - 2, y0 + CHROME_H + 13], fill=PANEL)
    d.line([x0 + 1, y0 + CHROME_H, x1 - 1, y0 + CHROME_H], fill=BORDER, width=2)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx, cy = x0 + 24 + i * 24, y0 + CHROME_H // 2
        d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=c)
    draw_center(d, (x0 + x1) / 2, y0 + 29, title, DIM, 19, style="mono")


STEPS = ["理解需求", "写代码", "写测试", "跑测试", "修 bug", "再验证", "提交"]
CAPTIONS = [
    "① 理解需求：先看仓库里的版本号长什么样，再动手",
    "② 写代码：去掉后缀 → 按点拆开 → 逐段比较",
    "③ 写测试：相等、补丁号、后缀、主版本，各测一种情况",
    "④ 跑测试：4 个挂了 1 个 —— 6.1.118 竟然比 6.1.75 小？",
    "⑤ 修 bug：字符串是逐字符比较的，\"118\" < \"75\"，要先转成整数",
    "⑥ 再验证：同样的 4 个测试，全部通过",
    "⑦ 提交：代码和测试一起进 git",
]


def make_base():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    draw_text(d, 40, 62, "✻", ORANGE, 38)
    x = draw_text(d, 86, 60, "Claude Code", FG, 30, "sans", stroke=1)
    draw_text(d, x + 4, 60, " · 写代码的过程", DIM, 30, "sans")
    draw_window(d, EDITOR, "编辑器 — oneplus-pad-pro-kernel")
    draw_window(d, TERM, "claude — ~/gg/oneplus-pad-pro-kernel")
    return img


LEXER = PythonLexer()


def token_color(t):
    if t in Token.Comment:
        return SYN["comment"]
    if t in Token.Literal.String:
        return SYN["string"]
    if t in Token.Literal.Number:
        return SYN["number"]
    if t in Token.Keyword or t in Token.Operator.Word:
        return SYN["keyword"]
    if t in Token.Name.Function:
        return SYN["func"]
    if t in Token.Name.Builtin or t in Token.Name.Namespace:
        return SYN["builtin"]
    if t in Token.Operator:
        return SYN["op"]
    if t in Token.Name:
        return SYN["name"]
    return SYN["punct"]


# ---------------------------------------------------------------- 画面状态

class Editor:
    def __init__(self):
        self.files = {}          # 文件名 -> 内容，按打开顺序
        self.active = None
        self.cursor = 0
        self.marks = {}          # (文件名, 行号) -> 整行背景色
        self.selection = None    # (起, 止) 字符下标

    def insert(self, s):
        t = self.files[self.active]
        self.files[self.active] = t[:self.cursor] + s + t[self.cursor:]
        self.cursor += len(s)


class Term:
    def __init__(self):
        self.lines = []          # 每行：[片段列表, 背景色, 续行缩进]；片段 = [文字, 颜色, 粗体]
        self.input = ""
        self.focus = False       # 输入框里是否显示光标
        self.spinner = None      # 转圈时旁边的文字


NO_LINE_START = "，。、：；！？）》」"


def carry_over(buf, ch, line_empty):
    """折行时要从行尾挪到下一行的部分：不拆开短的英文单词，中文标点不放行首。"""
    if ch.isascii() and not ch.isspace():
        m = re.search(r"(?<![!-~])[!-~]{1,20}$", buf)
        if m and (m.start() or not line_empty):
            return m.group()
    if ch in NO_LINE_START and len(buf) > 1:
        return buf[-1]
    return ""


def wrap(segs, max_w, indent):
    """按像素宽度把一行折成多行，续行前面补 indent 个空格。"""
    lines, cur, w = [], [], 0.0
    ind_w = indent * char_w(" ", "mono", T_SIZE)
    for text, color, bold in segs:
        buf = ""
        for ch in text:
            cw = char_w(ch, font_kind(ch, "mono", bold), T_SIZE)
            if w + cw > max_w and (buf or cur):
                carry = carry_over(buf, ch, not cur)
                buf = buf[:len(buf) - len(carry)]
                if buf:
                    cur.append((buf, color, bold))
                lines.append(cur)
                cur, w = [(" " * indent, FG, False)], ind_w + text_w(carry, T_SIZE, bold=bold)
                buf = carry
                if ch == " ":
                    continue
            buf += ch
            w += cw
        if buf:
            cur.append((buf, color, bold))
    lines.append(cur)
    return lines


def draw_segs(d, x, y, segs):
    for text, color, bold in segs:
        x = draw_text(d, x, y, text, color, T_SIZE, bold=bold)
    return x


def draw_editor(d, ed, blink):
    x0, y0, x1, y1 = EDITOR
    tab_y = y0 + CHROME_H + 1
    d.rectangle([x0 + 2, tab_y, x1 - 2, tab_y + TAB_H], fill=TABBAR)
    tx = x0 + 2
    for name in ed.files:
        tw = text_w(name, 20) + 48
        on = name == ed.active
        if on:
            d.rectangle([tx, tab_y, tx + tw, tab_y + TAB_H], fill=PANEL)
            d.rectangle([tx, tab_y, tx + tw, tab_y + 2], fill=ORANGE)
        draw_text(d, tx + 24, tab_y + 30, name, FG if on else DIM, 20)
        d.line([tx + tw, tab_y, tx + tw, tab_y + TAB_H], fill=BORDER)
        tx += tw + 1
    d.line([x0 + 2, tab_y + TAB_H, x1 - 2, tab_y + TAB_H], fill=BORDER)
    if ed.active is None:
        draw_center(d, (x0 + x1) / 2, (y0 + y1) / 2 + 20, "还没有打开的文件", FAINT, 26)
        return

    text = ed.files[ed.active]
    starts = [0] + [m.end() for m in re.finditer("\n", text)]
    cur_line = text.count("\n", 0, ed.cursor)
    code_x = x0 + GUTTER
    top = tab_y + TAB_H + 14

    def baseline(i):
        return top + i * C_LH + C_LH - 10

    for i, start in enumerate(starts):
        ly = top + i * C_LH
        mark = ed.marks.get((ed.active, i + 1))
        if mark:
            d.rectangle([x0 + 2, ly, x1 - 2, ly + C_LH], fill=mark)
        elif i == cur_line:
            d.rectangle([x0 + 2, ly, x1 - 2, ly + C_LH], fill=LINE_HL)
        num = str(i + 1)
        draw_text(d, code_x - 26 - text_w(num, C_SIZE - 3), baseline(i), num,
                  FG if i == cur_line else FAINT, C_SIZE - 3)

    if ed.selection:
        s, e = ed.selection
        for i, start in enumerate(starts):
            end = starts[i + 1] - 1 if i + 1 < len(starts) else len(text)
            a, b = max(s, start), min(e, end)
            if a < b:
                xa = code_x + text_w(text[start:a], C_SIZE)
                xb = xa + text_w(text[a:b], C_SIZE)
                d.rectangle([xa, top + i * C_LH + 3, xb, top + (i + 1) * C_LH - 3], fill=SEL)

    x, line = code_x, 0
    for _, ttype, value in LEXER.get_tokens_unprocessed(text):
        color = token_color(ttype)
        for j, part in enumerate(value.split("\n")):
            if j:
                line, x = line + 1, code_x
            if part.strip():
                x = draw_text(d, x, baseline(line), part, color, C_SIZE)
            else:
                x += text_w(part, C_SIZE)

    if blink:
        cx = code_x + text_w(text[starts[cur_line]:ed.cursor], C_SIZE)
        ly = top + cur_line * C_LH
        d.rectangle([cx, ly + 5, cx + 2, ly + C_LH - 5], fill=FG)


def draw_term(d, term, blink, spin):
    x0, y0, x1, y1 = TERM
    left = x0 + 24
    max_w = x1 - 24 - left

    # 输入框
    in_lines = wrap([["> ", DIM, False], [term.input, FG, False]], max_w - 20, 2)
    box_top = y1 - 18 - 20 - len(in_lines) * T_LH
    d.rounded_rectangle([x0 + 14, box_top, x1 - 14, y1 - 18], 10, outline=BORDER, width=2)
    ex = left
    for i, vl in enumerate(in_lines):
        ex = draw_segs(d, left + 4, box_top + 10 + (i + 1) * T_LH - 8, vl)
    if term.focus and blink:
        by = box_top + 10 + (len(in_lines) - 1) * T_LH
        d.rectangle([ex + 1, by + 5, ex + 12, by + T_LH - 3], fill=FG)

    # 对话记录，放不下时只显示最后几行（相当于往上滚）
    vis = []
    for segs, bg, indent in term.lines:
        vis += [(vl, bg) for vl in wrap(segs, max_w, indent)]
    if term.spinner:
        vis.append(([(SPIN[spin] + " ", ORANGE, False), (term.spinner, ORANGE_SOFT, False)], None))
    top = y0 + CHROME_H + 16
    rows = int((box_top - 12 - top) // T_LH)
    for i, (vl, bg) in enumerate(vis[-rows:]):
        ly = top + i * T_LH
        if bg:
            d.rectangle([x0 + 14, ly + 1, x1 - 14, ly + T_LH - 1], fill=bg)
        draw_segs(d, left, ly + T_LH - 8, vl)


def draw_topbar(d, step):
    widths = [text_w(s, 21, "sans") + 42 for s in STEPS]
    x = 1880 - sum(widths) - 10 * (len(STEPS) - 1)
    for i, label in enumerate(STEPS):
        state = "current" if i == step else "done" if i < step else "todo"
        x += draw_chip(d, x, 26, label, state) + 10


def draw_caption(d, text):
    if not text:
        return
    tw = text_w(text, CAP_SIZE, "sans")
    d.rounded_rectangle([W / 2 - tw / 2 - 36, 936, W / 2 + tw / 2 + 36, 1034], 18,
                        fill=(24, 27, 36), outline=BORDER, width=2)
    draw_center(d, W / 2, 998, text, FG, CAP_SIZE)


def draw_intro(d, t):
    draw_center(d, W / 2, 400, "✻", ORANGE, 120, style="mono")
    draw_center(d, W / 2, 540, "看 Claude 写代码", FG, 84, stroke=1)
    draw_center(d, W / 2, 624, "一个真实的小任务：比较内核版本号 6.1.118 和 6.1.75", DIM, 36)
    draw_center(d, W / 2, 1000, "画面里的代码、测试输出和 git 提交都是真实运行的结果，打字速度为演示放慢",
                FAINT, 24)


def draw_outro(d, t):
    draw_center(d, W / 2, 300, "写代码的过程", FG, 64, stroke=1)
    size, gap = 28, 64
    widths = [text_w(s, size, "sans") + 2 * size for s in STEPS]
    x = (W - sum(widths) - gap * (len(STEPS) - 1)) / 2
    shown = int(t / 0.22) + 1
    for i, label in enumerate(STEPS[:shown]):
        draw_chip(d, x, 390, label, "current" if i == 4 else "done", size)
        x += widths[i]
        if i < len(STEPS) - 1:
            draw_center(d, x + gap / 2, 390 + size + 11, "→", FAINT, 30, style="mono")
        x += gap
    if t > 1.8:
        draw_center(d, W / 2, 600, "测试先挂了一个，才揪出 \"118\" < \"75\" 这种肉眼很难发现的 bug。", FG, 36)
    if t > 2.6:
        draw_center(d, W / 2, 664, "改完再跑一遍，全部通过才提交。", FG, 36)
    draw_center(d, W / 2, 1000, "由 coding-video/make_video.py 生成 · 代码、测试输出和提交记录均为真实运行结果",
                FAINT, 24)


# ---------------------------------------------------------------- 输出

class FFmpegSink:
    def __init__(self, path):
        self.path = path
        self.proc = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
             "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-tune", "animation",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)],
            stdin=subprocess.PIPE)

    def write(self, n, img):
        self.proc.stdin.write(img.tobytes())

    def close(self):
        self.proc.stdin.close()
        if self.proc.wait():
            sys.exit("ffmpeg 编码失败")


class PreviewSink:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    def write(self, n, img):
        if n % FPS == 0:
            img.save(self.folder / f"{n // FPS:03d}s.png")

    def close(self):
        pass


class Director:
    def __init__(self, sink):
        self.sink = sink
        self.n = 0
        self.ed, self.term = Editor(), Term()
        self.step, self.caption = 0, ""
        self.base = make_base()
        self.black = Image.new("RGB", (W, H), (0, 0, 0))
        self.rng = random.Random(7)

    # 画一帧主场景
    def render(self, blink, spin, fade):
        img = self.base.copy()
        d = ImageDraw.Draw(img)
        draw_topbar(d, self.step)
        draw_editor(d, self.ed, blink)
        draw_term(d, self.term, blink, spin)
        draw_caption(d, self.caption)
        return img if fade >= 1 else Image.blend(self.black, img, fade)

    def emit(self, img):
        self.sink.write(self.n, img)
        self.n += 1
        if self.n % (FPS * 10) == 0:
            print(f"  已渲染 {self.n // FPS} 秒", file=sys.stderr)

    def show(self, frames, typing=False, fade=None):
        """当前状态保持 frames 帧；只有光标闪烁和转圈会变，所以同样的组合只画一次。"""
        cache = {}
        for i in range(frames):
            blink = typing or (self.n // 15) % 2 == 0
            spin = (self.n // 3) % len(SPIN) if self.term.spinner else 0
            f = 1.0 if fade is None else fade(i / max(frames - 1, 1))
            key = (blink, spin, f)
            if key not in cache:
                cache[key] = self.render(blink, spin, f)
            self.emit(cache[key])

    def wait(self, sec):
        self.show(round(sec * FPS))

    def fade_in(self, sec):
        self.show(round(sec * FPS), fade=lambda p: round(p, 2))

    def fade_out(self, sec):
        self.show(round(sec * FPS), fade=lambda p: round(1 - p, 2))

    def card(self, draw, sec, fade=0.6):
        """片头片尾：draw(d, 秒) 画一帧，前后各淡入淡出 fade 秒。"""
        frames = round(sec * FPS)
        for i in range(frames):
            t = i / FPS
            img = Image.new("RGB", (W, H), BG)
            draw(ImageDraw.Draw(img), t)
            a = min(1.0, t / fade, (sec - t) / fade)
            self.emit(img if a >= 1 else Image.blend(self.black, img, max(a, 0)))

    def typed(self, keys, insert, cps):
        """按 cps（每秒字符数）带一点随机节奏地逐个输入。"""
        t, done = 0.0, 0
        for k in keys:
            insert(k)
            t += self.rng.uniform(0.5, 1.5) / cps + (0.12 if k.startswith("\n") else 0)
            due = int(t * FPS) - done
            if due > 0:
                self.show(due, typing=True)
                done += due
        self.show(1, typing=True)

    # ---- 终端里的动作
    def set_step(self, i):
        self.step, self.caption = i, CAPTIONS[i]

    def add(self, segs, bg=None, indent=2):
        line = [[list(s) for s in segs], bg, indent]
        self.term.lines.append(line)
        return line

    def type_prompt(self, text):
        self.term.focus = True
        self.typed(text, lambda ch: setattr(self.term, "input", self.term.input + ch), cps=9)
        self.wait(0.7)
        self.add([("> ", DIM, False), (self.term.input, FG, False)])
        self.term.input, self.term.focus = "", False
        self.wait(0.3)

    def think(self, sec, label="思考中…"):
        self.term.spinner = label
        self.wait(sec)
        self.term.spinner = None

    def say(self, text):
        self.add([])
        seg = self.add([("● ", FG, False), ("", FG, False)])[0][1]
        self.typed(text, lambda ch: seg.__setitem__(0, seg[0] + ch), cps=40)

    def tool(self, name, args):
        self.add([])
        return self.add([("● ", DIM, False), (name, FG, True), (f"({args})", DIM, False)])

    def result(self, call, lines, ok=True, colorize=None, bgs=None):
        call[0][0][1] = GREEN if ok else RED
        for i, text in enumerate(lines):
            color = colorize(text) if colorize else DIM
            prefix = "  └ " if i == 0 else "    "
            self.add([(prefix, DIM, False), (text, color, False)],
                     bg=bgs[i] if bgs else None, indent=4)
            self.show(2)

    # ---- 编辑器里的动作
    def open_file(self, name):
        self.ed.files.setdefault(name, "")
        self.ed.active = name
        self.ed.cursor = len(self.ed.files[name])

    def type_code(self, text, cps=60):
        # 换行和后面的缩进当成一次按键，像编辑器的自动缩进
        keys = re.findall(r"\n *|.", text, re.S)
        self.typed(keys, self.ed.insert, cps)


def pytest_color(line):
    if "failed" in line or line.startswith(("E ", "FAILED")):
        return RED
    if "passed" in line:
        return GREEN
    if line.startswith(("=", "_")):
        return DIM
    return FG


def script(v, real):
    ed = v.ed

    v.card(draw_intro, 4.5)

    # ① 理解需求
    v.set_step(0)
    v.fade_in(0.6)
    v.wait(0.6)
    v.type_prompt(PROMPT)
    v.think(1.5)
    v.say("先看看仓库里的版本号是什么格式。")
    call = v.tool("Grep", f'"{GREP_PATTERN}", build.sh')
    v.think(0.8, "搜索中…")
    v.result(call, real["grep"], colorize=lambda _: FG)
    v.wait(1.5)
    v.say("版本号 = 点分数字（6.1.118）+ 后缀（-android14-11）。"
          "思路：去掉后缀，按点拆开，再逐段比较。")
    v.wait(2.0)

    # ② 写代码
    v.set_step(1)
    call = v.tool("Write", "kver.py")
    v.term.spinner = "写入中…"
    v.open_file("kver.py")
    v.type_code(KVER_BUGGY)
    v.term.spinner = None
    v.result(call, [f"已写入 {KVER_BUGGY.count(chr(10))} 行"])
    v.wait(1.5)

    # ③ 写测试
    v.set_step(2)
    v.say("再写测试：相等、补丁号、后缀、主版本，各测一种情况。")
    call = v.tool("Write", "test_kver.py")
    v.term.spinner = "写入中…"
    v.open_file("test_kver.py")
    v.type_code(TEST_KVER)
    v.term.spinner = None
    v.result(call, [f"已写入 {TEST_KVER.count(chr(10))} 行"])
    v.wait(1.2)

    # ④ 跑测试
    v.set_step(3)
    call = v.tool("Bash", PYTEST_CMD)
    v.think(1.2, "运行中…")
    v.result(call, real["failed"], ok=False, colorize=pytest_color)
    ed.cursor = TEST_KVER.index(FAIL_ASSERT)
    ed.marks[("test_kver.py", line_no(TEST_KVER, FAIL_ASSERT))] = RED_BG
    v.wait(3.5)

    # ⑤ 修 bug
    v.set_step(4)
    v.think(1.2)
    bug_at = KVER_BUGGY.index(BUG_LINE) + len("    return ")
    v.open_file("kver.py")
    ed.cursor = bug_at
    ed.marks[("kver.py", line_no(KVER_BUGGY, BUG_LINE))] = YELLOW_BG
    ed.selection = (bug_at, bug_at + len(BUG_EXPR))
    v.say('test_patch_level 挂了：compare("6.1.118", "6.1.75") 返回了 -1。'
          'parse() 拆出来的是字符串，"118" < "75" 是逐字符比较的（"1" < "7"）。'
          "要先转成整数再比。")
    v.wait(3.0)
    call = v.tool("Update", "kver.py")
    ed.selection = None
    v.wait(0.4)
    v.type_code(FIX_PREFIX, cps=30)
    ed.cursor += len(BUG_EXPR)
    v.show(4)
    v.type_code(FIX_SUFFIX, cps=30)
    ed.marks[("kver.py", line_no(KVER_BUGGY, BUG_LINE))] = GREEN_BG
    n = line_no(KVER_BUGGY, BUG_LINE)
    v.result(call, ["已修改 kver.py：1 行增加，1 行删除",
                    f"{n:>3} - {BUG_LINE}",
                    f"{n:>3} + {FIX_LINE}"],
             colorize=lambda s: DIM if s.startswith("已") else FG,
             bgs=[None, RED_BG, GREEN_BG])
    v.wait(2.0)

    # ⑥ 再验证
    v.set_step(5)
    call = v.tool("Bash", PYTEST_CMD)
    v.think(1.0, "运行中…")
    v.result(call, real["passed"], colorize=pytest_color)
    del ed.marks[("test_kver.py", line_no(TEST_KVER, FAIL_ASSERT))]
    v.wait(2.5)

    # ⑦ 提交
    v.set_step(6)
    call = v.tool("Bash", f'git add kver.py test_kver.py && git commit -m "{COMMIT_MSG}"')
    v.think(0.9, "运行中…")
    v.result(call, real["commit"], colorize=lambda _: FG)
    v.wait(0.8)
    v.say("完成：compare() 能正确处理补丁号和后缀，4 个测试全部通过，已提交。")
    v.wait(3.5)
    v.fade_out(0.6)

    v.card(draw_outro, 6.5)


def main():
    args = sys.argv[1:]
    if args[:1] == ["--preview"]:
        sink = PreviewSink(args[1] if len(args) > 1 else "preview")
    else:
        sink = FFmpegSink(args[0] if args else HERE / "claude-coding-process.mp4")
    print("真实运行 grep / pytest / git …", file=sys.stderr)
    real = run_for_real()
    print("开始渲染", file=sys.stderr)
    v = Director(sink)
    script(v, real)
    sink.close()
    print(f"完成：{v.n} 帧，{v.n / FPS:.1f} 秒", file=sys.stderr)


if __name__ == "__main__":
    main()
