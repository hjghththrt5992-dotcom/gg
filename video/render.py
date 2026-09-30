"""Frame renderer: drives stage.html in headless Chromium, one PNG per frame, in parallel."""
import glob
import json
import multiprocessing as mp
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE = (HERE / "stage.html").as_uri()


def chrome_path():
    hits = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))
    return hits[-1] if hits else None  # None -> Playwright's own browser


def _worker(args):
    idx, n, frames, tl_json, out_dir, fps = args
    from playwright.sync_api import sync_playwright

    tl = json.loads(tl_json)
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=chrome_path(), args=["--no-sandbox", "--disable-gpu"])
        page = br.new_page(viewport={"width": tl["width"], "height": tl["height"]}, device_scale_factor=1)
        page.goto(STAGE)
        page.evaluate("tl => setTimeline(tl)", tl)
        for f in frames[idx::n]:
            page.evaluate("t => render(t)", f / fps)
            page.screenshot(path=str(out_dir / f"{f:05d}.png"), type="png")
        br.close()
    return idx


def render_frames(tl, out_dir, workers=4, only=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = list(only) if only is not None else list(range(int(tl["duration"] * tl["fps"]) + 1))
    tl_json = json.dumps(tl, ensure_ascii=False)
    n = min(workers, len(frames))
    with mp.get_context("spawn").Pool(n) as pool:
        for _ in pool.imap_unordered(_worker, [(i, n, frames, tl_json, out_dir, tl["fps"]) for i in range(n)]):
            pass
    return len(frames)
