"""
clean.py — Physics-Trans v2.0
output 디렉토리의 캐시 및 중간 파일을 초기화한다.
smoke 테스트 서브디렉토리(smoke_*)도 함께 정리한다.

사용법:
  python clean.py            # output_dir 기준 (smoke_* 포함)
  python clean.py --all      # figures 디렉토리까지 완전 초기화
  python clean.py --smoke    # smoke_* 서브디렉토리만 삭제
"""

import argparse
import glob
import os
import shutil
import yaml


def main():
    # 항상 clean.py가 있는 디렉토리(프로젝트 루트)를 기준으로 실행
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    parser = argparse.ArgumentParser(description="Physics-Trans 캐시 초기화")
    parser.add_argument("--config", default="config.yaml", help="설정 파일 경로")
    parser.add_argument("--all", action="store_true", help="figures 디렉토리까지 완전 초기화")
    parser.add_argument("--smoke", action="store_true", help="smoke_* 서브디렉토리만 삭제")
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    output_dir  = config.get("output_dir", "output")
    figures_dir = config.get("figures_dir", os.path.join(output_dir, "figures"))
    cache_file  = config.get("cache_file",  os.path.join(output_dir, "translated_blocks.json"))

    # ── output 내 모든 서브디렉토리 삭제 (figures 제외) ──────────────────
    for entry in os.listdir(output_dir):
        full = os.path.join(output_dir, entry)
        if os.path.isdir(full) and entry != os.path.basename(figures_dir):
            shutil.rmtree(full)
            print(f"삭제: {full}/")

    # ── 로그 파일 삭제 ────────────────────────────────────────────────────
    for p in glob.glob(os.path.join(output_dir, "log_*.txt")):
        os.remove(p)
        print(f"삭제: {p}")

    if args.smoke:
        print("완료.")
        return

    # ── 중간 파일 삭제 ────────────────────────────────────────────────────
    targets = ["paper.json", "translated.json", os.path.basename(cache_file)]
    for fname in targets:
        p = os.path.join(output_dir, fname)
        if os.path.exists(p):
            os.remove(p)
            print(f"삭제: {p}")

    # ── 번역 결과물 (PDF / LaTeX 보조 파일) 삭제 ─────────────────────────
    for ext in ("*.pdf", "*.tex", "*.aux", "*.log", "*.out", "*.toc", "*.bib"):
        for p in glob.glob(os.path.join(output_dir, ext)):
            os.remove(p)
            print(f"삭제: {p}")

    # ── figures 디렉토리 초기화 ───────────────────────────────────────────
    if os.path.isdir(figures_dir):
        shutil.rmtree(figures_dir)
        print(f"삭제: {figures_dir}/")
    os.makedirs(figures_dir, exist_ok=True)
    print(f"생성: {figures_dir}/")

    print("완료.")


if __name__ == "__main__":
    main()
