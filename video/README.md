# 光标先生的自我介绍

55 秒竖屏（1080×1920）短视频：一个会打错字、会吐槽自己的终端光标，替 Claude 做自我介绍。
成片：[`out/claude_intro.mp4`](out/claude_intro.mp4)

## 重新生成

```bash
pip install -r requirements.txt
python build.py                 # 完整出片 -> out/claude_intro.mp4
python build.py --at 9.6 33.6   # 只渲这些时间点的预览帧 -> out/stills/
python build.py --audio-only    # 只合成音轨 -> out/audio.wav
```

首次运行会从 GitHub Releases 下载约 160 MB 的离线中文语音模型（sherpa-onnx 的 melo-tts）。
渲染用系统里的 Chromium（Playwright），4 核约 3 分钟。

## 结构

| 文件 | 作用 |
|---|---|
| `script.py` | 分镜即代码：台词、打字节奏、屏幕事件、音效点、字幕，全部由真实配音时长算出，画面与声音天然对齐 |
| `stage.html` | 画面：`render(t)` 是纯函数，给时间就还原出那一帧（终端、光标先生、字幕、CRT 效果） |
| `audio.py` | 离线 TTS、合成键盘音效、8-bit 背景乐、人声闪避混音、口型包络 |
| `render.py` / `build.py` | 并行逐帧截图、ffmpeg 合成 |

改台词只需要改 `script.py` 里 `say([...])` 的文字。

## 备注

- 配音默认零噪声（`TTS_NOISE=0`），同样的文字每次生成同样的声音，出片可复现。
- 词典里没有 "Anthropic"，`audio.py` 里补了一条读音（`LEXICON_PATCH`）。
- 这个离线模型的英文带口音，所以画面上始终有逐字高亮的硬字幕。
