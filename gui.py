"""
gui.py — Physics-Trans v2.0 GUI
실행: python gui.py  또는  더블클릭(gui_runner.pyw)
"""

import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import yaml

# ── 프로젝트 루트 (이 파일이 있는 폴더) ────────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT_DIR, "config.yaml")

# stdout 파싱 패턴
_RE_STAGE1 = re.compile(r"\[1/3\]")
_RE_STAGE2 = re.compile(r"\[2/3\]")
_RE_STAGE3 = re.compile(r"\[3/3\]")
_RE_TRANS_PROGRESS = re.compile(r"\[translator\]\s+(\d+)/(\d+)")
_RE_DONE = re.compile(r"완료\s*→")


def _load_config(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


class PhysicsTransGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.config = _load_config(CONFIG_PATH)

        self.root.title("Physics-Trans v2.0")
        self.root.geometry("780x580")
        self.root.resizable(True, True)

        # ── 상태 변수 ────────────────────────────────────────────────────
        self.pdf_path = tk.StringVar()
        self.output_dir = tk.StringVar(
            value=os.path.join(ROOT_DIR, self.config.get("output_dir", "output"))
        )
        self.auto_open_viewer = tk.BooleanVar(value=True)

        self.progress_var = tk.DoubleVar(value=0.0)
        self.status_var = tk.StringVar(value="준비됨")
        self.elapsed_var = tk.StringVar(value="경과: 0분 00초")

        # 설정 탭 변수
        self.cfg_project_id = tk.StringVar(value=self.config.get("project_id", ""))
        self.cfg_location = tk.StringVar(value=self.config.get("location", "global"))
        self.cfg_model = tk.StringVar(value=self.config.get("model", "gemini-3-flash-preview"))
        self.cfg_max_workers = tk.StringVar(value=str(self.config.get("max_workers", 5)))
        self.cfg_style = tk.StringVar(value=self.config.get("translation_style", "합니다체"))
        self.cfg_main_font = tk.StringVar(value=self.config.get("main_font", "UnBatang"))

        # 내부 상태
        self._proc: subprocess.Popen | None = None
        self._q: queue.Queue = queue.Queue()
        self._timer_id = None
        self._start_time: float | None = None
        self._running = False

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ──────────────────────────────────────────────────────────────────────
    # UI 구성
    # ──────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        main_frame = ttk.Frame(nb, padding=10)
        nb.add(main_frame, text="  메인  ")
        self._build_main_tab(main_frame)

        settings_frame = ttk.Frame(nb, padding=10)
        nb.add(settings_frame, text="  설정  ")
        self._build_settings_tab(settings_frame)

    def _build_main_tab(self, frame: ttk.Frame):
        # PDF 파일 선택
        ttk.Label(frame, text="PDF 파일:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.pdf_path, width=55).grid(
            row=0, column=1, padx=4, sticky="ew"
        )
        ttk.Button(frame, text="찾기", command=self._select_pdf, width=6).grid(
            row=0, column=2
        )

        # 출력 폴더
        ttk.Label(frame, text="출력 폴더:").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.output_dir, width=55).grid(
            row=1, column=1, padx=4, sticky="ew"
        )
        ttk.Button(frame, text="찾기", command=self._select_output_dir, width=6).grid(
            row=1, column=2
        )

        # 옵션 체크박스
        opt_frame = ttk.Frame(frame)
        opt_frame.grid(row=2, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Checkbutton(opt_frame, text="완료 후 뷰어 열기", variable=self.auto_open_viewer).pack(
            side=tk.LEFT, padx=4
        )

        # 버튼 행
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=3, column=0, columnspan=3, pady=8)
        self.start_btn = ttk.Button(
            btn_frame, text="번역 시작", command=self._start, width=14
        )
        self.start_btn.pack(side=tk.LEFT, padx=4)
        self.stop_btn = ttk.Button(
            btn_frame, text="중단", command=self._stop, width=8, state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="초기화", command=self._clean, width=8).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_frame, text="뷰어 열기", command=self._open_viewer, width=10).pack(
            side=tk.LEFT, padx=4
        )

        ttk.Separator(frame, orient="horizontal").grid(
            row=4, column=0, columnspan=3, sticky="ew", pady=4
        )

        # 단계 레이블 + 경과 시간
        status_row = ttk.Frame(frame)
        status_row.grid(row=5, column=0, columnspan=3, sticky="ew")
        ttk.Label(status_row, textvariable=self.status_var, foreground="gray").pack(
            side=tk.LEFT
        )
        ttk.Label(status_row, textvariable=self.elapsed_var, foreground="gray").pack(
            side=tk.RIGHT
        )

        # 진행 바
        self.progress_bar = ttk.Progressbar(
            frame, variable=self.progress_var, maximum=100, length=600
        )
        self.progress_bar.grid(row=6, column=0, columnspan=3, sticky="ew", pady=4)

        # 로그 텍스트박스
        log_frame = ttk.Frame(frame)
        log_frame.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=4)
        self.log_text = tk.Text(
            log_frame, height=12, state=tk.DISABLED, wrap=tk.WORD,
            bg="white", fg="black", insertbackground="black",
            font=("Consolas", 9),
        )
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=sb.set)

        # 색상 태그
        self.log_text.tag_configure("warn",    foreground="#b07d00")
        self.log_text.tag_configure("error",   foreground="#cc0000")
        self.log_text.tag_configure("success", foreground="#006600")
        self.log_text.tag_configure("info",    foreground="#0055cc")

        # 로그 지우기 버튼
        ttk.Button(frame, text="로그 지우기", command=self._clear_log, width=10).grid(
            row=8, column=2, sticky="e", pady=2
        )

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(7, weight=1)

    def _build_settings_tab(self, frame: ttk.Frame):
        fields = [
            ("project_id",       "Project ID:",      self.cfg_project_id,   None),
            ("location",         "Location:",         self.cfg_location,     ["global", "us-central1", "asia-northeast1"]),
            ("model",            "모델:",              self.cfg_model,        ["gemini-3-flash-preview", "gemini-2.5-flash", "gemini-2.0-flash"]),
            ("max_workers",      "Max Workers:",      self.cfg_max_workers,  None),
            ("translation_style","번역 스타일:",        self.cfg_style,        ["합니다체", "해요체", "한다체"]),
            ("main_font",        "한국어 폰트:",        self.cfg_main_font,    ["UnBatang", "NanumMyeongjo", "NanumGothic"]),
        ]

        for i, (_, label, var, values) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=i, column=0, sticky="w", pady=5, padx=4)
            if values:
                w = ttk.Combobox(frame, textvariable=var, values=values, width=34, state="readonly")
            else:
                w = ttk.Entry(frame, textvariable=var, width=36)
            w.grid(row=i, column=1, sticky="w", padx=4)

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=len(fields), column=0, columnspan=2, pady=16)
        ttk.Button(btn_row, text="설정 저장", command=self._save_config, width=14).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Button(btn_row, text="기본값 복원", command=self._restore_defaults, width=14).pack(
            side=tk.LEFT, padx=6
        )

        ttk.Label(
            frame, text="저장하면 config.yaml에 반영됩니다.", foreground="gray"
        ).grid(row=len(fields) + 1, column=0, columnspan=2, sticky="w", padx=4)

    # ──────────────────────────────────────────────────────────────────────
    # 이벤트 핸들러
    # ──────────────────────────────────────────────────────────────────────

    def _select_pdf(self):
        path = filedialog.askopenfilename(
            title="PDF 파일 선택",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self.pdf_path.set(path)

    def _select_output_dir(self):
        path = filedialog.askdirectory(title="출력 폴더 선택")
        if path:
            self.output_dir.set(path)

    def _clear_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _clean(self):
        import glob, shutil
        out = self.output_dir.get().strip()
        if not out:
            return
        if not messagebox.askyesno(
            "초기화 확인", "출력 폴더의 모든 번역 결과물과 중간 파일을 삭제합니다.\n계속하시겠습니까?"
        ):
            return
        deleted = []
        # 중간 파일
        for name in ("paper.json", "translated.json", "translated_blocks.json"):
            p = os.path.join(out, name)
            if os.path.exists(p):
                os.remove(p)
                deleted.append(name)
        # 컴파일 결과물 및 로그 파일
        for ext in ("*.pdf", "*.tex", "*.aux", "*.log", "*.out", "*.bib", "*.xdv", "log_*.txt"):
            for p in glob.glob(os.path.join(out, ext)):
                try:
                    os.remove(p)
                    deleted.append(os.path.basename(p))
                except PermissionError:
                    self._log(f"삭제 실패 (파일 열림): {os.path.basename(p)}", "warn")
        # figures 폴더
        figures = os.path.join(out, "figures")
        if os.path.isdir(figures):
            shutil.rmtree(figures)
            deleted.append("figures/")
        self._log("초기화: " + (", ".join(deleted) if deleted else "삭제할 파일 없음"), "info")
        self.progress_var.set(0.0)
        self.status_var.set("초기화 완료")

    def _save_config(self):
        self.config["project_id"] = self.cfg_project_id.get().strip()
        self.config["location"] = self.cfg_location.get().strip()
        self.config["model"] = self.cfg_model.get().strip()
        try:
            self.config["max_workers"] = int(self.cfg_max_workers.get())
        except ValueError:
            pass
        self.config["translation_style"] = self.cfg_style.get().strip()
        self.config["main_font"] = self.cfg_main_font.get().strip()
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.dump(self.config, f, allow_unicode=True, default_flow_style=False)
            messagebox.showinfo("저장 완료", "config.yaml에 저장되었습니다.")
        except OSError as e:
            messagebox.showerror("저장 오류", str(e))

    def _restore_defaults(self):
        defaults = {
            "project_id": "", "location": "global",
            "model": "gemini-3-flash-preview", "max_workers": "5",
            "translation_style": "합니다체", "main_font": "UnBatang",
        }
        self.cfg_project_id.set(defaults["project_id"])
        self.cfg_location.set(defaults["location"])
        self.cfg_model.set(defaults["model"])
        self.cfg_max_workers.set(defaults["max_workers"])
        self.cfg_style.set(defaults["translation_style"])
        self.cfg_main_font.set(defaults["main_font"])

    def _open_viewer(self):
        viewer_path = os.path.join(ROOT_DIR, "viewer.py")
        if not os.path.exists(viewer_path):
            messagebox.showerror("뷰어 오류", "viewer.py를 찾을 수 없습니다.")
            return
        subprocess.Popen(
            [sys.executable, viewer_path],
            cwd=ROOT_DIR,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

    # ──────────────────────────────────────────────────────────────────────
    # 번역 실행 / 중단
    # ──────────────────────────────────────────────────────────────────────

    def _start(self):
        pdf = self.pdf_path.get().strip()
        if not pdf:
            messagebox.showwarning("입력 오류", "PDF 파일을 선택하세요.")
            return
        if not os.path.exists(pdf):
            messagebox.showerror("파일 오류", f"파일을 찾을 수 없습니다:\n{pdf}")
            return

        out_dir = self.output_dir.get().strip() or os.path.join(ROOT_DIR, "output")
        os.makedirs(out_dir, exist_ok=True)

        cmd = [sys.executable, os.path.join(ROOT_DIR, "main.py"), pdf,
               "--config", CONFIG_PATH,
               "--out-dir", out_dir]

        self._reset_ui()
        self._running = True
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self._start_timer()

        self._log(f"실행: {' '.join(cmd)}", "info")

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
                errors="replace",
                cwd=ROOT_DIR,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except FileNotFoundError as e:
            messagebox.showerror("실행 오류", str(e))
            self._finish()
            return

        threading.Thread(target=self._reader_thread, daemon=True).start()
        self.root.after(100, self._poll_queue)

    def _stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self.status_var.set("중단 요청 중...")
        self.stop_btn.configure(state=tk.DISABLED)

    def _on_close(self):
        if self._running:
            if not messagebox.askyesno("종료 확인", "번역이 실행 중입니다. 종료하시겠습니까?"):
                return
            self._stop()
        self.root.destroy()

    # ──────────────────────────────────────────────────────────────────────
    # subprocess I/O — 백그라운드 스레드
    # ──────────────────────────────────────────────────────────────────────

    def _reader_thread(self):
        """subprocess stdout을 한 글자씩 읽어 \r 경계로 라인 분리 후 queue에 넣는다."""
        buf = ""
        try:
            while True:
                ch = self._proc.stdout.read(1)
                if not ch:
                    break
                if ch == "\r":
                    # \r 단독: 현재 버퍼를 overwrite 마킹해서 queue에
                    if buf:
                        self._q.put(("overwrite", buf))
                        buf = ""
                elif ch == "\n":
                    self._q.put(("line", buf))
                    buf = ""
                else:
                    buf += ch
            if buf:
                self._q.put(("line", buf))
        finally:
            self._proc.wait()
            self._q.put(("done", self._proc.returncode))

    # ──────────────────────────────────────────────────────────────────────
    # UI 업데이트 — 메인 스레드 (after 루프)
    # ──────────────────────────────────────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                kind, data = self._q.get_nowait()
                if kind == "line":
                    self._handle_line(data)
                elif kind == "overwrite":
                    self._handle_overwrite(data)
                elif kind == "done":
                    self._on_proc_done(data)
                    return  # 더 이상 폴링 불필요
        except queue.Empty:
            pass

        if self._running:
            self.root.after(100, self._poll_queue)

    def _handle_line(self, line: str):
        tag = self._line_tag(line)
        self._append_log(line, tag)
        self._parse_progress(line)

    def _handle_overwrite(self, line: str):
        """마지막 로그 줄을 교체 (\r 오버라이트 패턴)."""
        self.log_text.configure(state=tk.NORMAL)
        # 마지막 줄 삭제
        self.log_text.delete("end-2l", "end-1l")
        self.log_text.configure(state=tk.DISABLED)
        tag = self._line_tag(line)
        self._append_log(line, tag)
        self._parse_progress(line)

    def _on_proc_done(self, returncode: int):
        self._finish()
        if returncode == 0:
            self.status_var.set("완료")
            self.progress_var.set(100.0)
            self._log("번역 파이프라인 완료", "success")
            if self.auto_open_viewer.get():
                self._open_viewer()
            out = self.output_dir.get().strip()
            if out and sys.platform == "win32":
                os.startfile(out)
        else:
            self.status_var.set(f"오류 (종료코드 {returncode})")
            self._log(f"프로세스 비정상 종료: code={returncode}", "error")
            messagebox.showerror("번역 오류", f"main.py가 비정상 종료되었습니다 (code={returncode}).\n로그를 확인하세요.")

    # ──────────────────────────────────────────────────────────────────────
    # 진행도 파싱
    # ──────────────────────────────────────────────────────────────────────

    def _parse_progress(self, line: str):
        if _RE_STAGE1.search(line):
            self.progress_var.set(0.0)
            self.status_var.set("[1/3] 추출 중...")
        elif _RE_STAGE2.search(line):
            self.progress_var.set(33.0)
            self.status_var.set("[2/3] 번역 중...")
        elif _RE_STAGE3.search(line):
            self.progress_var.set(66.0)
            self.status_var.set("[3/3] 조립 중...")
        elif _RE_DONE.search(line):
            self.progress_var.set(100.0)
            self.status_var.set("완료")
        else:
            m = _RE_TRANS_PROGRESS.search(line)
            if m:
                n, total = int(m.group(1)), int(m.group(2))
                if total > 0:
                    pct = 33.0 + (n / total) * 33.0
                    self.progress_var.set(min(pct, 66.0))
                    self.status_var.set(f"번역 중 {n}/{total}")

    # ──────────────────────────────────────────────────────────────────────
    # 헬퍼
    # ──────────────────────────────────────────────────────────────────────

    def _line_tag(self, line: str) -> str:
        lo = line.lower()
        if "error" in lo or "오류" in lo or "traceback" in lo or "exception" in lo:
            return "error"
        if "warning" in lo or "warn" in lo or "경고" in lo:
            return "warn"
        if "완료" in line or "✓" in line or "success" in lo:
            return "success"
        if line.startswith("[") or "중..." in line:
            return "info"
        return ""

    def _append_log(self, text: str, tag: str = ""):
        self.log_text.configure(state=tk.NORMAL)
        if tag:
            self.log_text.insert(tk.END, text + "\n", tag)
        else:
            self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _log(self, message: str, tag: str = ""):
        self._append_log(message, tag)

    def _reset_ui(self):
        self.progress_var.set(0.0)
        self.status_var.set("시작 중...")
        self.elapsed_var.set("경과: 0분 00초")
        self._clear_log()

    def _finish(self):
        self._running = False
        self._stop_timer()
        self.start_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)

    def _start_timer(self):
        self._start_time = time.time()
        self._tick_timer()

    def _tick_timer(self):
        if self._start_time is None:
            return
        elapsed = int(time.time() - self._start_time)
        m, s = divmod(elapsed, 60)
        self.elapsed_var.set(f"경과: {m}분 {s:02d}초")
        self._timer_id = self.root.after(1000, self._tick_timer)

    def _stop_timer(self):
        if self._timer_id is not None:
            self.root.after_cancel(self._timer_id)
            self._timer_id = None
        self._start_time = None


# ──────────────────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────────────────

def run():
    root = tk.Tk()
    app = PhysicsTransGUI(root)
    root.mainloop()


if __name__ == "__main__":
    run()
