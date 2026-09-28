"""网页问答界面（只用 Python 标准库，无需安装 Web 框架）。"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from kb_builder.chunker import chunk_header

PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>知识库问答</title>
<style>
  :root { --bg:#f7f7f5; --card:#fff; --text:#1f2328; --muted:#6b7280; --line:#e5e7eb; --accent:#2563eb; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#16181d; --card:#1f2229; --text:#e6e6e6; --muted:#9aa0aa; --line:#30343c; --accent:#6ea0ff; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:16px/1.7 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif; }
  main { max-width:760px; margin:0 auto; padding:24px 16px 64px; }
  h1 { font-size:22px; margin:0 0 4px; }
  .sub { color:var(--muted); font-size:13px; margin-bottom:20px; }
  form { display:flex; gap:8px; }
  input { flex:1; min-width:0; padding:10px 12px; font-size:16px; border:1px solid var(--line);
          border-radius:8px; background:var(--card); color:var(--text); }
  button { padding:10px 18px; font-size:16px; border:0; border-radius:8px; background:var(--accent);
           color:#fff; cursor:pointer; }
  button:disabled { opacity:.5; cursor:default; }
  .qa { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; margin-top:16px; }
  .q { font-weight:600; margin-bottom:8px; }
  .a { white-space:pre-wrap; word-break:break-word; }
  .a sup { color:var(--accent); font-weight:600; }
  .src { margin-top:12px; border-top:1px dashed var(--line); padding-top:8px; font-size:14px; color:var(--muted); }
  details { margin:4px 0; }
  details.cited summary { color:var(--text); }
  details p { white-space:pre-wrap; margin:6px 0 10px 16px; }
  summary { cursor:pointer; }
</style>
</head>
<body>
<main>
  <h1>知识库问答</h1>
  <div class="sub" id="info">加载中…</div>
  <form id="f"><input id="q" placeholder="输入问题，例如：LoRA 为什么能省显存？" autocomplete="off" autofocus>
  <button id="b">提问</button></form>
  <div id="list"></div>
</main>
<script>
const $ = s => document.querySelector(s);
const esc = s => s.replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
fetch("/api/info").then(r => r.json()).then(d => {
  $("#info").textContent = `模型：${d.model} ｜ 知识库：${d.docs} 篇文档 / ${d.chunks} 块 ｜ 检索：${d.mode}`;
});
$("#f").onsubmit = async e => {
  e.preventDefault();
  const question = $("#q").value.trim();
  if (!question) return;
  $("#b").disabled = true;
  const box = document.createElement("div");
  box.className = "qa";
  box.innerHTML = `<div class="q">${esc(question)}</div><div class="a">检索中…</div><div class="src"></div>`;
  $("#list").prepend(box);
  const a = box.querySelector(".a"), src = box.querySelector(".src");
  let answer = "", sources = [];
  const render = () => {
    a.innerHTML = esc(answer).replace(/\\[(\\d+)\\]/g, "<sup>[$1]</sup>");
    const cited = new Set([...answer.matchAll(/\\[(\\d+)\\]/g)].map(m => +m[1]));
    src.innerHTML = "参考资料：" + sources.map(s =>
      `<details class="${cited.has(s.n) ? "cited" : ""}"><summary>[${s.n}] ${esc(s.header)}` +
      `${cited.has(s.n) ? " ✓" : ""}</summary><p>${esc(s.text)}</p></details>`).join("");
  };
  try {
    const res = await fetch("/api/ask", {method: "POST", headers: {"Content-Type": "application/json"},
                                         body: JSON.stringify({question})});
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream: true});
      let i;
      while ((i = buf.indexOf("\\n")) >= 0) {
        const msg = JSON.parse(buf.slice(0, i)); buf = buf.slice(i + 1);
        if (msg.type === "sources") { sources = msg.data; a.textContent = "思考中…"; }
        else if (msg.type === "token") { answer += msg.data; render(); }
        else if (msg.type === "error") { answer += "\\n[出错] " + msg.data; render(); }
      }
    }
    render();
  } catch (err) {
    a.textContent = "请求失败：" + err;
  }
  $("#b").disabled = false;
  $("#q").select();
};
</script>
</body>
</html>
"""


def make_handler(rag, info: dict):
    lock = threading.Lock()  # 模型一次只处理一个问题

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _line(self, obj: dict):
            self.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
            self.wfile.flush()

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif self.path == "/api/info":
                self._send(200, json.dumps(info, ensure_ascii=False).encode("utf-8"), "application/json")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if self.path != "/api/ask":
                return self._send(404, b"not found", "text/plain")
            try:
                length = int(self.headers.get("Content-Length") or 0)
                question = str(json.loads(self.rfile.read(length) or b"{}").get("question", "")).strip()[:500]
            except (ValueError, AttributeError):
                return self._send(400, b"bad request", "text/plain")
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                with lock:
                    contexts, stream = rag.ask(question)
                    self._line({"type": "sources", "data": [
                        {"n": i, "header": chunk_header(c), "doc": c["doc"], "text": c["text"]}
                        for i, c in enumerate(contexts, 1)]})
                    for piece in stream:
                        self._line({"type": "token", "data": piece})
                    self._line({"type": "done"})
            except (BrokenPipeError, ConnectionResetError):
                pass  # 浏览器提前关闭了页面
            except Exception as e:  # 把错误显示在页面上，方便排查
                try:
                    self._line({"type": "error", "data": str(e)})
                except OSError:
                    pass

    return Handler


def run_web(rag, host: str = "127.0.0.1", port: int = 8000) -> None:
    r = rag.retriever
    info = {
        "model": f"{rag.backend.label}（{rag.backend.name}）",
        "docs": len({c["doc"] for c in r.chunks}),
        "chunks": len(r.chunks),
        "mode": ("关键词+向量" if r.embedder else "仅关键词") + ("+重排" if r.reranker else ""),
    }
    server = ThreadingHTTPServer((host, port), make_handler(rag, info))
    print(f"[网页] 打开浏览器访问 http://{host}:{port}  （按 Ctrl+C 停止）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
