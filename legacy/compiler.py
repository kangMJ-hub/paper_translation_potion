import os
import shutil
import subprocess
import sys


def find_xelatex() -> str | None:
    """시스템에서 xelatex 실행 파일 경로를 찾는다."""
    return shutil.which("xelatex")


def parse_latex_log(log: str) -> list:
    """LaTeX 컴파일 로그에서 오류 라인을 추출한다."""
    errors = []
    for line in log.split("\n"):
        if line.startswith("!"):
            errors.append(line)
    return errors


def compile_latex(
    tex_path: str,
    output_dir: str,
    progress_callback=None,
) -> tuple:
    """xelatex으로 .tex 파일을 2회 컴파일한다. (success, errors) 반환."""
    xelatex = find_xelatex()
    if not xelatex:
        return False, ["xelatex을 찾을 수 없습니다. TeX Live가 설치되어 있는지 확인하세요."]

    # tex 파일이 있는 디렉토리에서 컴파일 (한글 경로 문제 회피)
    tex_dir = os.path.dirname(os.path.abspath(tex_path))
    tex_basename = os.path.splitext(os.path.basename(tex_path))[0]
    errors = []

    for run in range(1, 3):
        if progress_callback:
            progress_callback(f"XeLaTeX 컴파일 중 ({run}/2)...")

        try:
            result = subprocess.run(
                [
                    xelatex,
                    "-interaction=nonstopmode",
                    os.path.basename(tex_path),
                ],
                capture_output=True,
                text=True,
                cwd=tex_dir,
                timeout=120,
            )
            log_output = result.stdout + result.stderr
            run_errors = parse_latex_log(log_output)
            if run_errors:
                errors = run_errors

            if result.returncode != 0:
                if run == 1:
                    print(
                        f"[compiler] 1차 컴파일 오류 (2차 시도로 계속): {run_errors}",
                        file=sys.stderr,
                    )
                else:
                    return False, errors if errors else [f"컴파일 실패 (종료 코드: {result.returncode})"]

        except subprocess.TimeoutExpired as e:
            try:
                e.process.kill()
                e.process.communicate()
            except Exception:
                pass
            return False, ["컴파일 시간 초과 (120초). 문서 크기를 확인하세요."]
        except Exception as e:
            return False, [f"컴파일 실행 오류: {str(e)}"]

    pdf_path = os.path.join(tex_dir, f"{tex_basename}.pdf")
    if not os.path.exists(pdf_path):
        # xdvipdfmx 파일 잠금 오류 확인
        combined_log = ""
        log_file = os.path.join(tex_dir, f"{tex_basename}.log")
        if os.path.exists(log_file):
            with open(log_file, encoding="utf-8", errors="ignore") as f:
                combined_log = f.read()
        if "Unable to open" in combined_log or "xdvipdfmx:fatal" in combined_log:
            return False, ["PDF 파일이 다른 프로그램에서 열려 있어 저장할 수 없습니다.\n뷰어를 닫은 후 다시 시도하세요."]
        return False, errors + [f"{tex_basename}.pdf 파일이 생성되지 않았습니다."]

    return True, errors
