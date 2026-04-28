"""
gui.py — Physics-Trans v2.0 GUI (Modern Design)
필요 패키지: pip install customtkinter
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
from tkinter import filedialog, messagebox

import yaml

try:
    import customtkinter as ctk
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
except ImportError:
    _root = tk.Tk()
    _root.withdraw()
    messagebox.showerror(
        "패키지 필요",
        "modernized GUI를 사용하려면 다음 명령어를 실행하세요:\n\n"
        "pip install customtkinter"
    )
    _root.destroy()
    sys.exit(1)

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT_DIR, "config.yaml")

_RE_STAGE1 = re.compile(r"\[1/3\]")
_RE_STAGE2 = re.compile(r"\[2/3\]")
_RE_STAGE3 = re.compile(r"\[3/3\]")
_RE_TRANS_PROGRESS = re.compile(r"\[translator\]\s+(\d+)/(\d+)")
_RE_DONE = re.compile(r"완료\s*→")

# ── 색상 팔레트 (iOS/macOS 스타일) ──────────────────────────────────────────
BG        = "#F2F2F7"
CARD      = "#FFFFFF"
ACCENT    = "#007AFF"
ACCENT_H  = "#0056CC"
DANGER    = "#FF3B30"
DANGER_H  = "#D43028"
BORDER    = "#E5E5EA"
TEXT      = "#1C1C1E"
SECONDARY = "#8E8E93"
STAGE_DONE_BG  = "#D1F2DB"
STAGE_DONE_FG  = "#1A7A3A"


def _load_config(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


class PhysicsTransGUI:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.config = _load_config(CONFIG_PATH)

        self.root.title("Physics-Trans")
        self.root.geometry("860x680")
        self.root.resizable(True, True)
        self.root.configure(fg_color=BG)

        # ── 상태 변수 ────────────────────────────────────────────────────
        self.pdf_path = tk.StringVar()
        self.output_dir = tk.StringVar(
            value=os.path.join(ROOT_DIR, self.config.get("output_dir", "output"))
        )
        self.auto_open_viewer = tk.BooleanVar(value=True)
        self.status_var  = tk.StringVar(value="준비됨")
        self.elapsed_var = tk.StringVar(value="경과: 0분 00초")

        # 설정 탭 변수
        self.cfg_project_id  = tk.StringVar(value=self.config.get("project_id", ""))
        self.cfg_location    = tk.StringVar(value=self.config.get("location", "global"))
        self.cfg_model       = tk.StringVar(value=self.config.get("model", "gemini-3-flash-preview"))
        self.cfg_max_workers = tk.StringVar(value=str(self.config.get("max_workers", 5)))
        self.cfg_style       = tk.StringVar(value=self.config.get("translation_style", "합니다체"))
        self.cfg_main_font   = tk.StringVar(value=self.config.get("main_font", "UnBatang"))

        # 내부 상태
        self._proc: subprocess.Popen | None = None
        self._q: queue.Queue = queue.Queue()
        self._timer_id = None
        self._start_time: float | None = None
        self._running = False

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        # 타이틀 바
        titlebar = ctk.CTkFrame(self.root, fg_color=ACCENT, corner_radius=0, height=48)
        titlebar.pack(fill="x")
        titlebar.pack_propagate(False)
        ctk.CTkLabel(
            titlebar, text="Physics-Trans",
            font=ctk.CTkFont(size=17, weight="bold"), text_color="white",
        ).pack(side="left", padx=20)
        ctk.CTkLabel(
            titlebar, text="v2.0  ·  영어 물리 논문 → 한국어 PDF",
            font=ctk.CTkFont(size=12), text_color="#B8D4FF",
        ).pack(side="left")

        # 탭뷰
        self.tabview = ctk.CTkTabview(
            self.root, fg_color=BG,
            segmented_button_fg_color=BG,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT_H,
            segmented_button_unselected_color=BG,
            segmented_button_unselected_hover_color=BORDER,
            text_color=TEXT,
            corner_radius=0,
        )
        self.tabview.pack(fill="both", expand=True)

        self._build_main_tab(self.tabview.add("  메인  "))
        self._build_settings_tab(self.tabview.add("  설정  "))

    def _build_main_tab(self, tab):
        tab.configure(fg_color=BG)

        # ── 입력 카드 ────────────────────────────────────────────────────
        input_card = ctk.CTkFrame(tab, fg_color=CARD, corner_radius=12)
        input_card.pack(fill="x", padx=16, pady=(12, 0))

        self._file_row(input_card, "PDF 파일", self.pdf_path,
                       "번역할 PDF 파일 경로...", self._select_pdf, row=0)
        self._file_row(input_card, "출력 폴더", self.output_dir,
                       "번역 결과물 저장 위치...", self._select_output_dir, row=1)

        ctk.CTkCheckBox(
            input_card, text="완료 후 뷰어 자동 열기",
            variable=self.auto_open_viewer,
            fg_color=ACCENT, hover_color=ACCENT_H, border_color=BORDER,
            text_color=TEXT, font=ctk.CTkFont(size=12),
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=16, pady=(6, 14))

        input_card.columnconfigure(1, weight=1)

        # ── 버튼 행 ──────────────────────────────────────────────────────
        btn_frame = ctk.CTkFrame(tab, fg_color=BG)
        btn_frame.pack(fill="x", padx=16, pady=10)

        self.start_btn = ctk.CTkButton(
            btn_frame, text="  번역 시작", command=self._start,
            height=40, font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=ACCENT, hover_color=ACCENT_H,
        )
        self.start_btn.pack(side="left", padx=(0, 8))

        self.stop_btn = ctk.CTkButton(
            btn_frame, text="  중단", command=self._stop,
            height=40, font=ctk.CTkFont(size=13),
            fg_color=DANGER, hover_color=DANGER_H,
            state="disabled", width=90,
        )
        self.stop_btn.pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_frame, text="초기화", command=self._clean,
            height=40, font=ctk.CTkFont(size=12),
            fg_color="transparent", hover_color=BORDER,
            text_color=TEXT, border_width=1, border_color=BORDER, width=80,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_frame, text="뷰어 열기", command=self._open_viewer,
            height=40, font=ctk.CTkFont(size=12),
            fg_color="transparent", hover_color=BORDER,
            text_color=TEXT, border_width=1, border_color=BORDER, width=100,
        ).pack(side="left")

        # ── 진행 카드 ────────────────────────────────────────────────────
        prog_card = ctk.CTkFrame(tab, fg_color=CARD, corner_radius=12)
        prog_card.pack(fill="x", padx=16, pady=(0, 10))

        # 단계 표시기 (3개 pill)
        stage_outer = ctk.CTkFrame(prog_card, fg_color=CARD)
        stage_outer.pack(fill="x", padx=16, pady=(14, 8))

        self._stage_frames: list[ctk.CTkFrame] = []
        self._stage_lbls:   list[ctk.CTkLabel] = []
        for i, (num, name) in enumerate([("1", "추출"), ("2", "번역"), ("3", "조립")]):
            sf = ctk.CTkFrame(stage_outer, fg_color=BORDER, corner_radius=8, height=34)
            sf.pack(side="left", fill="x", expand=True, padx=(0, 6 if i < 2 else 0))
            sf.pack_propagate(False)
            lbl = ctk.CTkLabel(sf, text=f"{num}/3  {name}",
                               font=ctk.CTkFont(size=11), text_color=SECONDARY)
            lbl.place(relx=0.5, rely=0.5, anchor="center")
            self._stage_frames.append(sf)
            self._stage_lbls.append(lbl)

        # 진행 바
        self.progress_bar = ctk.CTkProgressBar(
            prog_card, fg_color=BORDER, progress_color=ACCENT,
            height=6, corner_radius=3,
        )
        self.progress_bar.pack(fill="x", padx=16, pady=(0, 8))
        self.progress_bar.set(0)

        # 상태 텍스트
        status_row = ctk.CTkFrame(prog_card, fg_color=CARD)
        status_row.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkLabel(status_row, textvariable=self.status_var,
                     font=ctk.CTkFont(size=12), text_color=SECONDARY, anchor="w",
                     ).pack(side="left")
        ctk.CTkLabel(status_row, textvariable=self.elapsed_var,
                     font=ctk.CTkFont(size=12), text_color=SECONDARY, anchor="e",
                     ).pack(side="right")

        # ── 로그 카드 ────────────────────────────────────────────────────
        log_card = ctk.CTkFrame(tab, fg_color=CARD, corner_radius=12)
        log_card.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        log_hdr = ctk.CTkFrame(log_card, fg_color=CARD)
        log_hdr.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(log_hdr, text="실행 로그",
                     font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT,
                     ).pack(side="left")
        ctk.CTkButton(
            log_hdr, text="지우기", command=self._clear_log,
            width=56, height=26,
            fg_color="transparent", hover_color=BORDER,
            text_color=SECONDARY, border_width=1, border_color=BORDER,
            font=ctk.CTkFont(size=11),
        ).pack(side="right")

        self.log_text = ctk.CTkTextbox(
            log_card, state="disabled", wrap="word",
            fg_color="#FAFAFA", text_color=TEXT,
            font=ctk.CTkFont(family="Consolas", size=10),
            corner_radius=8,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=SECONDARY,
        )
        self.log_text.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        # 내부 tk.Text에 컬러 태그 등록
        _tb = self.log_text._textbox
        _tb.tag_configure("warn",    foreground="#b07d00")
        _tb.tag_configure("error",   foreground="#cc0000")
        _tb.tag_configure("success", foreground="#1a7a3a")
        _tb.tag_configure("info",    foreground="#0055cc")

    def _file_row(self, parent, label: str, var: tk.StringVar,
                  placeholder: str, cmd, row: int):
        top_pad = 14 if row == 0 else 6
        ctk.CTkLabel(
            parent, text=label, font=ctk.CTkFont(size=12),
            text_color=SECONDARY, anchor="w",
        ).grid(row=row, column=0, sticky="w", padx=(16, 8), pady=(top_pad, 0))

        ctk.CTkEntry(
            parent, textvariable=var, placeholder_text=placeholder,
            border_color=BORDER, fg_color="white", text_color=TEXT,
            height=34, font=ctk.CTkFont(size=12),
        ).grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=(top_pad, 0))

        ctk.CTkButton(
            parent, text="찾기", command=cmd,
            width=58, height=34, font=ctk.CTkFont(size=12),
            fg_color=ACCENT, hover_color=ACCENT_H,
        ).grid(row=row, column=2, padx=(0, 16), pady=(top_pad, 0))

    def _build_settings_tab(self, tab):
        tab.configure(fg_color=BG)

        card = ctk.CTkFrame(tab, fg_color=CARD, corner_radius=12)
        card.pack(fill="x", padx=16, pady=16)

        fields = [
            ("Project ID:",  self.cfg_project_id,   None),
            ("Location:",    self.cfg_location,     ["global", "us-central1", "asia-northeast1"]),
            ("모델:",         self.cfg_model,        ["gemini-3-flash-preview", "gemini-2.5-flash", "gemini-2.0-flash"]),
            ("Max Workers:", self.cfg_max_workers,  None),
            ("번역 스타일:",  self.cfg_style,        ["합니다체", "해요체", "한다체"]),
            ("한국어 폰트:",  self.cfg_main_font,    ["UnBatang", "NanumMyeongjo", "NanumGothic"]),
        ]

        for i, (label, var, values) in enumerate(fields):
            top_pad = 16 if i == 0 else 8
            ctk.CTkLabel(
                card, text=label, font=ctk.CTkFont(size=12),
                text_color=SECONDARY, anchor="w",
            ).grid(row=i, column=0, sticky="w", padx=(16, 12), pady=(top_pad, 0))

            if values:
                w = ctk.CTkComboBox(
                    card, variable=var, values=values,
                    width=290, height=34, font=ctk.CTkFont(size=12),
                    border_color=BORDER, fg_color="white", text_color=TEXT,
                    button_color=ACCENT, button_hover_color=ACCENT_H,
                    dropdown_fg_color="white", dropdown_text_color=TEXT,
                )
            else:
                w = ctk.CTkEntry(
                    card, textvariable=var, width=290, height=34,
                    font=ctk.CTkFont(size=12),
                    border_color=BORDER, fg_color="white", text_color=TEXT,
                )
            w.grid(row=i, column=1, sticky="w", padx=(0, 16), pady=(top_pad, 0))

        btn_row = ctk.CTkFrame(card, fg_color=CARD)
        btn_row.grid(row=len(fields), column=0, columnspan=2,
                     sticky="w", padx=16, pady=16)

        ctk.CTkButton(
            btn_row, text="설정 저장", command=self._save_config,
            height=36, width=110, font=ctk.CTkFont(size=13),
            fg_color=ACCENT, hover_color=ACCENT_H,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            btn_row, text="기본값 복원", command=self._restore_defaults,
            height=36, width=110, font=ctk.CTkFont(size=13),
            fg_color="transparent", hover_color=BORDER,
            text_color=TEXT, border_width=1, border_color=BORDER,
        ).pack(side="left")

        ctk.CTkLabel(
            card, text="저장하면 config.yaml에 즉시 반영됩니다.",
            font=ctk.CTkFont(size=11), text_color=SECONDARY,
        ).grid(row=len(fields) + 1, column=0, columnspan=2,
               sticky="w", padx=16, pady=(0, 16))

    # ── 이벤트 핸들러 ────────────────────────────────────────────────────────

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
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _clean(self):
        import glob, shutil
        out = self.output_dir.get().strip()
        if not out:
            return
        if not messagebox.askyesno(
            "초기화 확인",
            "출력 폴더의 모든 번역 결과물과 중간 파일을 삭제합니다.\n계속하시겠습니까?"
        ):
            return
        deleted = []
        for name in ("paper.json", "translated.json", "translated_blocks.json"):
            p = os.path.join(out, name)
            if os.path.exists(p):
                os.remove(p)
                deleted.append(name)
        for ext in ("*.pdf", "*.tex", "*.aux", "*.log", "*.out", "*.bib", "*.xdv", "log_*.txt"):
            for p in glob.glob(os.path.join(out, ext)):
                try:
                    os.remove(p)
                    deleted.append(os.path.basename(p))
                except PermissionError:
                    self._log(f"삭제 실패 (파일 열림): {os.path.basename(p)}", "warn")
        figures = os.path.join(out, "figures")
        if os.path.isdir(figures):
            shutil.rmtree(figures)
            deleted.append("figures/")
        self._log("초기화: " + (", ".join(deleted) if deleted else "삭제할 파일 없음"), "info")
        self._set_progress(0.0)
        self.status_var.set("초기화 완료")

    def _save_config(self):
        self.config["project_id"]        = self.cfg_project_id.get().strip()
        self.config["location"]           = self.cfg_location.get().strip()
        self.config["model"]              = self.cfg_model.get().strip()
        self.config["translation_style"]  = self.cfg_style.get().strip()
        self.config["main_font"]          = self.cfg_main_font.get().strip()
        try:
            self.config["max_workers"] = int(self.cfg_max_workers.get())
        except ValueError:
            pass
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.dump(self.config, f, allow_unicode=True, default_flow_style=False)
            messagebox.showinfo("저장 완료", "config.yaml에 저장되었습니다.")
        except OSError as e:
            messagebox.showerror("저장 오류", str(e))

    def _restore_defaults(self):
        self.cfg_project_id.set("")
        self.cfg_location.set("global")
        self.cfg_model.set("gemini-3-flash-preview")
        self.cfg_max_workers.set("5")
        self.cfg_style.set("합니다체")
        self.cfg_main_font.set("UnBatang")

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

    # ── 번역 실행 / 중단 ─────────────────────────────────────────────────────

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
               "--config", CONFIG_PATH, "--out-dir", out_dir]

        self._reset_ui()
        self._running = True
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._start_timer()
        self._log(f"실행: {' '.join(cmd)}", "info")

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", cwd=ROOT_DIR,
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
        self.stop_btn.configure(state="disabled")

    def _on_close(self):
        if self._running:
            if not messagebox.askyesno("종료 확인", "번역이 실행 중입니다. 종료하시겠습니까?"):
                return
            self._stop()
        self.root.destroy()

    # ── subprocess I/O — 백그라운드 스레드 ──────────────────────────────────

    def _reader_thread(self):
        buf = ""
        try:
            while True:
                ch = self._proc.stdout.read(1)
                if not ch:
                    break
                if ch == "\r":
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

    # ── UI 업데이트 — 메인 스레드 ────────────────────────────────────────────

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
                    return
        except queue.Empty:
            pass
        if self._running:
            self.root.after(100, self._poll_queue)

    def _handle_line(self, line: str):
        self._append_log(line, self._line_tag(line))
        self._parse_progress(line)

    def _handle_overwrite(self, line: str):
        tag = self._line_tag(line)
        self.log_text.configure(state="normal")
        self.log_text._textbox.delete("end-2l", "end-1l")
        tb = self.log_text._textbox
        tb.insert("end", line + "\n", tag) if tag else tb.insert("end", line + "\n")
        tb.see("end")
        self.log_text.configure(state="disabled")
        self._parse_progress(line)

    def _on_proc_done(self, returncode: int):
        self._finish()
        if returncode == 0:
            self._set_progress(100.0)
            self._update_stages(4)   # 전체 완료 → 모든 단계 초록
            self.status_var.set("완료")
            self._log("번역 파이프라인 완료", "success")
            if self.auto_open_viewer.get():
                self._open_viewer()
            out = self.output_dir.get().strip()
            if out and sys.platform == "win32":
                os.startfile(out)
        else:
            self.status_var.set(f"오류 (종료코드 {returncode})")
            self._log(f"프로세스 비정상 종료: code={returncode}", "error")
            messagebox.showerror(
                "번역 오류",
                f"main.py가 비정상 종료되었습니다 (code={returncode}).\n로그를 확인하세요."
            )

    # ── 진행도 파싱 ──────────────────────────────────────────────────────────

    def _parse_progress(self, line: str):
        if _RE_STAGE1.search(line):
            self._set_progress(0.0)
            self.status_var.set("[1/3] 추출 중...")
            self._update_stages(1)
        elif _RE_STAGE2.search(line):
            self._set_progress(33.0)
            self.status_var.set("[2/3] 번역 중...")
            self._update_stages(2)
        elif _RE_STAGE3.search(line):
            self._set_progress(66.0)
            self.status_var.set("[3/3] 조립 중...")
            self._update_stages(3)
        elif _RE_DONE.search(line):
            self._set_progress(100.0)
            self.status_var.set("완료")
        else:
            m = _RE_TRANS_PROGRESS.search(line)
            if m:
                n, total = int(m.group(1)), int(m.group(2))
                if total > 0:
                    pct = 33.0 + (n / total) * 33.0
                    self._set_progress(min(pct, 66.0))
                    self.status_var.set(f"번역 중 {n}/{total}")

    def _update_stages(self, active: int):
        """단계 표시기 색상 업데이트.
        active=1→1단계 진행중, active=2→2단계 진행중, ..., active=4→전체 완료.
        """
        for i, (sf, lbl) in enumerate(zip(self._stage_frames, self._stage_lbls)):
            n = i + 1
            if n < active:
                sf.configure(fg_color=STAGE_DONE_BG)
                lbl.configure(text_color=STAGE_DONE_FG)
            elif n == active:
                sf.configure(fg_color=ACCENT)
                lbl.configure(text_color="white")
            else:
                sf.configure(fg_color=BORDER)
                lbl.configure(text_color=SECONDARY)

    # ── 헬퍼 ─────────────────────────────────────────────────────────────────

    def _set_progress(self, value: float):
        self.progress_bar.set(value / 100.0)

    def _line_tag(self, line: str) -> str:
        lo = line.lower()
        if "error" in lo or "오류" in lo or "traceback" in lo or "exception" in lo:
            return "error"
        if "warning" in lo or "warn" in lo or "경고" in lo:
            return "warn"
        if "완료" in line or "success" in lo:
            return "success"
        if line.startswith("[") or "중..." in line:
            return "info"
        return ""

    def _append_log(self, text: str, tag: str = ""):
        self.log_text.configure(state="normal")
        tb = self.log_text._textbox
        if tag:
            tb.insert("end", text + "\n", tag)
        else:
            tb.insert("end", text + "\n")
        tb.see("end")
        self.log_text.configure(state="disabled")

    def _log(self, message: str, tag: str = ""):
        self._append_log(message, tag)

    def _reset_ui(self):
        self._set_progress(0.0)
        self._update_stages(0)
        self.status_var.set("시작 중...")
        self.elapsed_var.set("경과: 0분 00초")
        self._clear_log()

    def _finish(self):
        self._running = False
        self._stop_timer()
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

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


# ── 진입점 ────────────────────────────────────────────────────────────────────

def run():
    root = ctk.CTk()
    PhysicsTransGUI(root)
    root.mainloop()


if __name__ == "__main__":
    run()
