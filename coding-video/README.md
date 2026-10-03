# 看 Claude 写代码

[`claude-coding-process.mp4`](claude-coding-process.mp4)（1920×1080，67 秒）演示 Claude 完成一个小任务的完整过程：
写一个比较内核版本号的函数，比如 `6.1.118` 和 `6.1.75`。

| 步骤 | 画面里发生了什么 |
| --- | --- |
| ① 理解需求 | 先 grep `build.sh`，看清版本号的格式：`6.1.118` 加 `-android14-11` 这样的后缀 |
| ② 写代码 | `kver.py`：去掉后缀，按点拆开，逐段比较 |
| ③ 写测试 | `test_kver.py`：相等、补丁号、后缀、主版本各一个用例 |
| ④ 跑测试 | 4 个挂了 1 个：`6.1.118` 被判成比 `6.1.75` 小 |
| ⑤ 修 bug | 拆出来的是字符串，`"118" < "75"` 是逐字符比较的，改成 `int` 再比 |
| ⑥ 再验证 | 4 个测试全部通过 |
| ⑦ 提交 | `git commit` |

视频里的 grep 结果、代码、pytest 输出和 git 提交都不是手写的台词：
[`make_video.py`](make_video.py) 先在临时目录里真的执行一遍（不会改动本仓库），再把真实输出逐帧画成视频。
打字动画是为了看清楚而放慢的，实际写文件是一次写入。

## 重新生成

```sh
pip install pillow pygments pytest
# 还需要 ffmpeg（带 libx264）和字体 fonts-dejavu-core、fonts-wqy-zenhei
python3 make_video.py                # 输出 claude-coding-process.mp4
python3 make_video.py --preview DIR  # 不编码，每秒存一帧 PNG，调画面用
```
