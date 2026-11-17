"""Local form page for the browser task; records submissions so the result can be verified."""
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

PORT = 8765
URL = f"http://127.0.0.1:{PORT}"

PAGE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>AI OS 测试表单</title>
<style>body{{font:16px sans-serif;max-width:420px;margin:60px auto}}label{{display:block;margin:16px 0}}</style>
</head><body>
<h2>报名表</h2>
<form method="post" action="/submit">
  <input type="hidden" name="token" value="{token}">
  <label>姓名 <input name="name"></label>
  <label>城市
    <select name="city">
      <option value="">请选择</option><option>北京</option><option>上海</option>
      <option>杭州</option><option>深圳</option>
    </select>
  </label>
  <label><input type="checkbox" name="agree" value="yes"> 我同意条款</label>
  <button type="submit">提交</button>
</form>
</body></html>"""


class FormServer:
    def __init__(self):
        self.tokens: set[str] = set()
        self.submissions: list[dict] = []
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> None:
        state = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                token = secrets.token_hex(8)
                state.tokens.add(token)
                self._send(PAGE.format(token=token))

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")
                fields = {k: v[0] for k, v in parse_qs(body).items()}
                fields["user_agent"] = self.headers.get("User-Agent", "")
                state.submissions.append(fields)
                self._send("<h2>提交成功</h2>")

            def _send(self, html: str):
                data = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
