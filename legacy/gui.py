import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import yaml


class PaperTranslatorGUI:
    def __init__(self, root: tk.Tk, config: dict, config_path: str):
        self.root = root
        self.config = config
        self.config_path = config_path

        self.root.title("논문 자동 번역기")
        self.root.geometry("680x500")
        self.root.resizable(True, True)

        # 상태 변수
        self.pdf_path = tk.StringVar()
        self.output_dir = tk.StringVar(
            value=os.path.join(os.path.dirname(os.path.abspath(config_path)), "output")
        )
        self.api_key = tk.StringVar(
            value=config.get("api", {}).get("key", "")
        )
        self.model_var = tk.StringVar(
            value=config.get("api", {}).get("model", "gemini-2.5-flash")
        )
        self.style_var = tk.StringVar(
            value=config.get("translation", {}).get("style", "존댓말 (합니다체)")
        )
        self.auto_open = tk.BooleanVar(value=True)
        self.progress_var = tk.DoubleVar(value=0.0)
        self.status_var = tk.StringVar(value="준비됨")
        self.elapsed_var = tk.StringVar(value="")
        self._timer_id = None
        self._start_time = None
        self._stop_event = threading.Event()

        self._build_ui()

    # ──────────────────────── UI 구성 ────────────────────────

    def _build_ui(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        main_frame = ttk.Frame(notebook, padding=12)
        notebook.add(main_frame, text="  메인  ")
        self._build_main_tab(main_frame)

        settings_frame = ttk.Frame(notebook, padding=12)
        notebook.add(settings_frame, text="  설정  ")
        self._build_settings_tab(settings_frame)

    def _build_main_tab(self, frame: ttk.Frame):
        # PDF 선택
        ttk.Label(frame, text="PDF 파일:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.pdf_path, width=52).grid(
            row=0, column=1, padx=4
        )
        ttk.Button(frame, text="찾아보기", command=self._select_pdf).grid(
            row=0, column=2
        )

        # 출력 폴더
        ttk.Label(frame, text="출력 폴더:").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.output_dir, width=52).grid(
            row=1, column=1, padx=4
        )
        ttk.Button(frame, text="찾아보기", command=self._select_output_dir).grid(
            row=1, column=2
        )

        # 완료 후 자동 열기
        ttk.Checkbutton(
            frame, text="완료 후 출력 폴더 열기", variable=self.auto_open
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=6)

        # 번역 시작 / 중단 버튼
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=3, column=0, columnspan=3, pady=10)
        self.start_btn = ttk.Button(
            btn_frame, text="번역 시작", command=self._start_translation, width=16
        )
        self.start_btn.pack(side=tk.LEFT, padx=6)
        self.stop_btn = ttk.Button(
            btn_frame, text="번역 중단", command=self._stop_translation,
            width=16, state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, padx=6)
        self.clean_btn = ttk.Button(
            btn_frame, text="초기화", command=self._clean_output, width=10
        )
        self.clean_btn.pack(side=tk.LEFT, padx=6)

        # 구분선
        ttk.Separator(frame, orient="horizontal").grid(
            row=4, column=0, columnspan=3, sticky="ew", pady=6
        )

        # 진행 상황
        ttk.Label(frame, text="진행 상황:").grid(row=5, column=0, sticky="w")
        self.progress_bar = ttk.Progressbar(
            frame, variable=self.progress_var, maximum=100, length=400
        )
        self.progress_bar.grid(row=5, column=1, columnspan=2, sticky="ew", padx=4)

        ttk.Label(frame, textvariable=self.status_var, foreground="gray").grid(
            row=6, column=0, columnspan=2, sticky="w", pady=4
        )
        ttk.Label(frame, textvariable=self.elapsed_var, foreground="gray").grid(
            row=6, column=2, sticky="e", pady=4
        )

        # 로그 텍스트박스
        self.log_text = tk.Text(frame, height=8, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=4)
        scrollbar = ttk.Scrollbar(frame, command=self.log_text.yview)
        scrollbar.grid(row=7, column=3, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(7, weight=1)

    def _build_settings_tab(self, frame: ttk.Frame):
        # API 키
        ttk.Label(frame, text="Gemini API 키:").grid(row=0, column=0, sticky="w", pady=6)
        self.api_key_entry = ttk.Entry(
            frame, textvariable=self.api_key, width=52, show="●"
        )
        self.api_key_entry.grid(row=0, column=1, padx=4)
        ttk.Button(frame, text="표시/숨김", command=self._toggle_api_key_visibility).grid(
            row=0, column=2
        )

        # 모델 선택
        ttk.Label(frame, text="Gemini 모델:").grid(row=1, column=0, sticky="w", pady=6)
        model_combo = ttk.Combobox(
            frame,
            textvariable=self.model_var,
            values=["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash", "gemini-3-flash-preview"],
            width=30,
            state="readonly",
        )
        model_combo.grid(row=1, column=1, sticky="w", padx=4)

        # 번역 스타일
        ttk.Label(frame, text="번역 스타일:").grid(row=2, column=0, sticky="w", pady=6)
        style_combo = ttk.Combobox(
            frame,
            textvariable=self.style_var,
            values=["존댓말 (합니다체)", "반말 (해요체)"],
            width=30,
            state="readonly",
        )
        style_combo.grid(row=2, column=1, sticky="w", padx=4)

        # 저장 버튼
        ttk.Button(frame, text="설정 저장", command=self._save_settings, width=20).grid(
            row=3, column=0, columnspan=3, pady=16
        )

        ttk.Label(
            frame,
            text="API 키는 config.yaml에 저장됩니다.",
            foreground="gray",
        ).grid(row=4, column=0, columnspan=3, sticky="w")

    # ──────────────────────── 이벤트 핸들러 ────────────────────────

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

    def _stop_translation(self):
        self._stop_event.set()
        self.stop_btn.configure(state=tk.DISABLED)
        self._update_status("중단 요청 중...")

    def _clean_output(self):
        import shutil
        output_dir = self.output_dir.get().strip()
        if not output_dir:
            return
        if not messagebox.askyesno("초기화 확인", "출력 폴더의 모든 번역 결과물을 삭제합니다.\n계속하시겠습니까?"):
            return
        deleted = []
        for folder in ("cache", "figures"):
            path = os.path.join(output_dir, folder)
            if os.path.exists(path):
                shutil.rmtree(path)
                deleted.append(folder + "/")
        locked = []
        for ext in ("*.tex", "*.pdf", "*.aux", "*.log", "*.out", "*.xdv"):
            import glob
            for f in glob.glob(os.path.join(output_dir, ext)):
                try:
                    os.remove(f)
                    deleted.append(os.path.basename(f))
                except PermissionError:
                    locked.append(os.path.basename(f))
        if locked:
            messagebox.showwarning("파일 잠금", f"다음 파일이 다른 프로그램에서 열려 있어 삭제할 수 없습니다:\n" + "\n".join(locked) + "\n\n뷰어를 닫은 후 다시 초기화하세요.")
        self._reset_progress()
        self.status_var.set("초기화 완료")
        if deleted:
            self._log("초기화 완료: " + ", ".join(deleted))

    def _toggle_api_key_visibility(self):
        current = self.api_key_entry.cget("show")
        self.api_key_entry.configure(show="" if current == "●" else "●")

    def _save_settings(self):
        self.config.setdefault("api", {})["key"] = self.api_key.get()
        self.config.setdefault("api", {})["model"] = self.model_var.get()
        self.config.setdefault("translation", {})["style"] = self.style_var.get()
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.dump(self.config, f, allow_unicode=True, default_flow_style=False)
            messagebox.showinfo("저장 완료", "설정이 저장되었습니다.")
        except OSError as e:
            messagebox.showerror("저장 오류", f"설정 파일을 저장할 수 없습니다:\n{e}")

    def _start_translation(self):
        pdf = self.pdf_path.get().strip()
        if not pdf:
            messagebox.showwarning("입력 오류", "PDF 파일을 선택하세요.")
            return
        if not os.path.exists(pdf):
            messagebox.showerror("파일 오류", f"파일을 찾을 수 없습니다:\n{pdf}")
            return
        api_key = self.api_key.get().strip()
        if not api_key:
            messagebox.showwarning("설정 오류", "설정 탭에서 Gemini API 키를 입력하세요.")
            return

        self.config.setdefault("api", {})["key"] = api_key
        self.config.setdefault("api", {})["model"] = self.model_var.get()
        self.config.setdefault("translation", {})["style"] = self.style_var.get()

        # 출력 디렉토리 미리 생성
        output_dir = self.output_dir.get().strip()
        try:
            os.makedirs(os.path.join(output_dir, "cache"), exist_ok=True)
            os.makedirs(os.path.join(output_dir, "figures"), exist_ok=True)
        except OSError as e:
            messagebox.showerror("디렉토리 오류", f"출력 폴더를 생성할 수 없습니다:\n{e}")
            return

        self._stop_event.clear()
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.clean_btn.configure(state=tk.DISABLED)
        self._reset_progress()
        self._start_timer()
        thread = threading.Thread(target=self._run_pipeline, daemon=True)
        thread.start()

    # ──────────────────────── 파이프라인 ────────────────────────

    def _run_pipeline(self):
        import traceback
        from pdf_parser import parse_pdf, save_parsed_blocks, load_parsed_blocks
        from translator import translate_blocks, save_translated_blocks
        from latex_builder import build_latex
        from compiler import compile_latex

        pdf_path = self.pdf_path.get().strip()
        output_dir = self.output_dir.get().strip()
        figures_dir = os.path.join(output_dir, "figures")

        try:
            # Step 1: PDF 파싱
            cached_blocks = load_parsed_blocks(output_dir)
            if cached_blocks:
                self._log("캐시된 파싱 결과를 사용합니다.")
                blocks = cached_blocks
            else:
                self._update_status("PDF 파싱 중...")
                blocks = parse_pdf(
                    pdf_path, output_dir,
                    progress_callback=self._parse_progress
                )
                save_parsed_blocks(blocks, output_dir)
                self._log(f"PDF 파싱 완료: {len(blocks)}개 블록 추출")

            self._set_progress(33)

            # Step 2: 번역
            self._update_status("번역 중...")
            translated = translate_blocks(
                blocks, self.config, output_dir,
                progress_callback=self._translate_progress,
                stop_event=self._stop_event,
            )
            save_translated_blocks(translated, output_dir)
            self._log("번역 완료")
            self._set_progress(66)

            # Step 3: LaTeX 빌드
            self._update_status("LaTeX 파일 생성 중...")
            tex_path, latex_errors = build_latex(
                translated, self.config, output_dir, figures_dir, pdf_path
            )
            if latex_errors:
                self._log("LaTeX 경고:\n" + "\n".join(latex_errors))
            self._log(f"LaTeX 파일 생성: {tex_path}")
            self._set_progress(80)

            # Step 4: 컴파일
            self._update_status("XeLaTeX 컴파일 중...")
            success, compile_errors = compile_latex(
                tex_path, output_dir,
                progress_callback=self._update_status
            )
            if success:
                self._cleanup_temp_files(output_dir)
                self._set_progress(100)
                self._update_status("완료!")
                self._log("번역 및 컴파일 완료!")
                self.root.after(0, lambda: messagebox.showinfo(
                    "완료", f"번역이 완료되었습니다.\n출력 폴더: {output_dir}"
                ))
                if self.auto_open.get():
                    self.root.after(0, lambda: self._open_output_folder(output_dir))
            else:
                self._set_progress(90)
                error_msg = "\n".join(compile_errors)
                self._update_status("컴파일 오류 발생")
                self._log(f"컴파일 오류:\n{error_msg}")
                self.root.after(0, lambda: messagebox.showerror(
                    "컴파일 오류",
                    f"XeLaTeX 컴파일 실패:\n{error_msg}\n\n"
                    f".tex 파일은 생성되었습니다:\n{tex_path}"
                ))

        except InterruptedError:
            self._update_status("번역 중단됨")
            self._log("사용자가 번역을 중단했습니다. (번역된 내용은 캐시에 저장됨)")
            self.root.after(0, lambda: messagebox.showinfo("중단", "번역이 중단되었습니다.\n지금까지 번역된 내용은 캐시에 저장되어 다음 실행 시 이어집니다."))
        except Exception as e:
            tb = traceback.format_exc()
            self._update_status("오류 발생")
            self._log(f"오류:\n{tb}")
            self.root.after(0, lambda: messagebox.showerror("오류", str(e)))

        finally:
            self.root.after(0, lambda: self.start_btn.configure(state=tk.NORMAL))
            self.root.after(0, lambda: self.stop_btn.configure(state=tk.DISABLED))
            self.root.after(0, lambda: self.clean_btn.configure(state=tk.NORMAL))
            self._stop_timer()

    # ──────────────────────── 헬퍼 ────────────────────────

    def _reset_progress(self):
        self.progress_var.set(0.0)
        self.status_var.set("시작 중...")
        self.elapsed_var.set("")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _start_timer(self):
        import time
        self._start_time = time.time()
        self._tick_timer()

    def _tick_timer(self):
        if self._start_time is None:
            return
        import time
        elapsed = int(time.time() - self._start_time)
        m, s = divmod(elapsed, 60)
        self.elapsed_var.set(f"{m}분 {s:02d}초")
        self._timer_id = self.root.after(1000, self._tick_timer)

    def _stop_timer(self):
        if self._timer_id is not None:
            self.root.after_cancel(self._timer_id)
            self._timer_id = None
        self._start_time = None

    def _set_progress(self, value: float):
        self.root.after(0, lambda: self.progress_var.set(value))

    def _update_status(self, text: str):
        self.root.after(0, lambda: self.status_var.set(text))

    def _log(self, message: str):
        def _append():
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)
        self.root.after(0, _append)

    def _parse_progress(self, current: int, total: int, message: str):
        pct = (current / total * 33) if total > 0 else 0
        self._set_progress(pct)
        self._update_status(message)

    def _translate_progress(self, current: int, total: int, message: str):
        pct = 33 + (current / total * 33) if total > 0 else 33
        self._set_progress(pct)
        self._update_status(message)

    def _cleanup_temp_files(self, output_dir: str):
        """캐시, 작업 폴더, 그림 폴더 등 임시 파일을 삭제한다."""
        import shutil
        for folder in ("cache", "figures"):
            folder_path = os.path.join(output_dir, folder)
            if os.path.exists(folder_path):
                shutil.rmtree(folder_path)
        self._log("임시 파일 삭제 완료 (cache, work, figures)")

    def _open_output_folder(self, path: str):
        import subprocess
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            self._log(f"출력 폴더 열기 실패: {e}")
