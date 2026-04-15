"""
viewer.py — 원본/번역본 PDF 나란히 비교 뷰어
실행: python viewer.py
브라우저: http://localhost:8765
"""

import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"

HTML = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>Physics-Trans Viewer</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }

  /* ── 헤더 ── */
  header { background: #16213e; padding: 12px 20px; display: flex; align-items: center; gap: 16px; border-bottom: 2px solid #0f3460; flex-shrink: 0; }
  header h1 { font-size: 1.1rem; color: #e94560; letter-spacing: 1px; white-space: nowrap; }
  #pair-select { flex: 1; max-width: 480px; padding: 6px 10px; border-radius: 6px; border: 1px solid #0f3460; background: #0f3460; color: #e0e0e0; font-size: 0.9rem; cursor: pointer; }
  #pair-select option { background: #16213e; }
  .badge { font-size: 0.75rem; background: #0f3460; padding: 3px 8px; border-radius: 12px; white-space: nowrap; }
  #status { font-size: 0.8rem; color: #888; margin-left: auto; white-space: nowrap; }

  /* ── 레이블 바 ── */
  .label-bar { display: flex; background: #16213e; border-bottom: 1px solid #0f3460; flex-shrink: 0; }
  .label-bar div { flex: 1; text-align: center; padding: 6px; font-size: 0.8rem; font-weight: 600; }
  .label-bar .orig  { color: #4fc3f7; border-right: 1px solid #0f3460; }
  .label-bar .trans { color: #81c784; }

  /* ── 뷰어 ── */
  .viewer { display: flex; flex: 1; overflow: hidden; }
  .pane { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  .pane + .pane { border-left: 2px solid #0f3460; }
  iframe { flex: 1; border: none; background: #fff; }

  /* ── 빈 상태 ── */
  .empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; color: #555; }
  .empty svg { width: 64px; height: 64px; opacity: 0.3; }
  .empty p { font-size: 0.9rem; }

  /* ── 페이지 동기 버튼 ── */
  .sync-btn { position: fixed; bottom: 20px; right: 20px; background: #e94560; color: #fff; border: none; border-radius: 50%; width: 48px; height: 48px; font-size: 1.2rem; cursor: pointer; box-shadow: 0 4px 12px rgba(0,0,0,0.5); z-index: 100; title: "페이지 동기"; }
  .sync-btn:hover { background: #c73652; }
</style>
</head>
<body>

<header>
  <h1>📄 Physics-Trans Viewer</h1>
  <select id="pair-select"><option value="">— 논문 선택 —</option></select>
  <span class="badge" id="count-badge">0 쌍</span>
  <span id="status">로딩 중…</span>
</header>

<div class="label-bar">
  <div class="orig">원본 (Original)</div>
  <div class="trans">번역본 (Korean)</div>
</div>

<div class="viewer" id="viewer">
  <div class="empty" id="empty-state">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/>
      <line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/>
    </svg>
    <p>위에서 논문을 선택하세요</p>
  </div>
</div>

<button class="sync-btn" title="스크롤 동기화 (미지원 안내)" onclick="alert('PDF iframe 간 스크롤 동기화는 브라우저 보안 정책으로 지원되지 않습니다.\n각 패널을 독립적으로 스크롤하세요.')">⇅</button>

<script>
const sel = document.getElementById('pair-select');
const viewer = document.getElementById('viewer');
const emptyState = document.getElementById('empty-state');
const status = document.getElementById('status');
const countBadge = document.getElementById('count-badge');

async function loadPairs() {
  try {
    const res = await fetch('/api/pairs');
    const pairs = await res.json();
    countBadge.textContent = pairs.length + ' 쌍';
    status.textContent = pairs.length === 0 ? '번역본 없음' : '준비됨';

    pairs.forEach(p => {
      const opt = document.createElement('option');
      opt.value = JSON.stringify(p);
      opt.textContent = p.label;
      sel.appendChild(opt);
    });
  } catch(e) {
    status.textContent = '오류: ' + e.message;
  }
}

sel.addEventListener('change', () => {
  if (!sel.value) {
    viewer.innerHTML = '';
    viewer.appendChild(emptyState);
    return;
  }
  const p = JSON.parse(sel.value);
  viewer.innerHTML = '';

  const makePane = (url, cls) => {
    const pane = document.createElement('div');
    pane.className = 'pane';
    if (url) {
      const iframe = document.createElement('iframe');
      iframe.src = url;
      iframe.title = cls === 'orig' ? '원본' : '번역본';
      pane.appendChild(iframe);
    } else {
      const msg = document.createElement('div');
      msg.className = 'empty';
      msg.innerHTML = '<p>원본 파일 없음</p>';
      pane.appendChild(msg);
    }
    return pane;
  };

  viewer.appendChild(makePane(p.orig ? '/file?path=' + encodeURIComponent(p.orig) : null, 'orig'));
  viewer.appendChild(makePane('/file?path=' + encodeURIComponent(p.trans), 'trans'));
});

loadPairs();
</script>
</body>
</html>
"""


def find_pairs():
    """output 하위 폴더에서 원본+번역본 PDF 쌍을 탐색한다."""
    pairs = []

    if not OUTPUT_DIR.exists():
        return pairs

    # 1) 서브폴더 내 쌍 (test_*, smoke_* 등)
    for subdir in sorted(OUTPUT_DIR.iterdir()):
        if not subdir.is_dir():
            continue
        pdfs = sorted(subdir.glob("*.pdf"))
        trans = [p for p in pdfs if "_번역" in p.name]
        origs = [p for p in pdfs if "_번역" not in p.name]

        for t in trans:
            # 번역본 이름에서 원본 추정: "X_번역.pdf" → "X.pdf"
            orig_name = t.stem.replace("_번역", "") + ".pdf"
            orig = next((o for o in origs if o.name == orig_name), None)
            # 원본이 output에 없으면 test_paper/ 에서 탐색
            if orig is None:
                candidate = BASE_DIR / "test_paper" / orig_name
                if candidate.exists():
                    orig = candidate

            pairs.append({
                "label": f"[{subdir.name}] {t.stem.replace('_번역','')}",
                "orig":  str(orig.relative_to(BASE_DIR)).replace("\\", "/") if orig else None,
                "trans": str(t.relative_to(BASE_DIR)).replace("\\", "/"),
            })

    # 2) output 루트에 바로 있는 번역본 (legacy)
    for t in sorted(OUTPUT_DIR.glob("*_번역.pdf")):
        orig_name = t.stem.replace("_번역", "") + ".pdf"
        orig = BASE_DIR / "test_paper" / orig_name
        pairs.append({
            "label": f"[output] {t.stem.replace('_번역','')}",
            "orig":  str(orig.relative_to(BASE_DIR)).replace("\\", "/") if orig.exists() else None,
            "trans": str(t.relative_to(BASE_DIR)).replace("\\", "/"),
        })

    return pairs


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 콘솔 로그 억제

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self._send(200, "text/html; charset=utf-8", HTML.encode())

        elif path == "/api/pairs":
            data = json.dumps(find_pairs(), ensure_ascii=False).encode()
            self._send(200, "application/json", data)

        elif path == "/file":
            from urllib.parse import parse_qs
            qs = parse_qs(parsed.query)
            rel = unquote(qs.get("path", [""])[0])
            abs_path = (BASE_DIR / rel).resolve()

            # 경로 탈출 방지
            try:
                abs_path.relative_to(BASE_DIR.resolve())
            except ValueError:
                self._send(403, "text/plain", b"Forbidden")
                return

            if not abs_path.exists() or not abs_path.suffix.lower() == ".pdf":
                self._send(404, "text/plain", b"Not found")
                return

            data = abs_path.read_bytes()
            self._send(200, "application/pdf", data)

        else:
            self._send(404, "text/plain", b"Not found")

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = 8765
    server = HTTPServer(("localhost", port), Handler)
    url = f"http://localhost:{port}"
    print(f"[viewer] 서버 시작: {url}")
    print(f"[viewer] 종료: Ctrl+C")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[viewer] 종료")
        sys.exit(0)
