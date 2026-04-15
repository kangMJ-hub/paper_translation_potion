"""
main.py — Physics-Trans v2.0 CLI 진입점
사용법: python main.py <paper.pdf> [--config config.yaml]
"""

import argparse
import json
import os
import sys

import yaml


def main() -> None:
    parser = argparse.ArgumentParser(
        description="영어 물리 논문 PDF → 한국어 PDF 자동 번역"
    )
    parser.add_argument("pdf", help="입력 PDF 경로")
    parser.add_argument(
        "--config", default="config.yaml", help="설정 파일 경로 (기본값: config.yaml)"
    )
    parser.add_argument(
        "--skip-extract", action="store_true",
        help="추출 건너뜀 — output/paper.json이 이미 있을 때 사용"
    )
    parser.add_argument(
        "--skip-translate", action="store_true",
        help="번역 건너뜀 — output/translated.json이 이미 있을 때 사용"
    )
    parser.add_argument(
        "--out-dir", default=None,
        help="출력 디렉토리 (config.yaml의 output_dir 덮어씀)"
    )
    parser.add_argument(
        "--clear-cache", action="store_true",
        help="번역 시작 전 블록 캐시(translated_blocks.json)를 초기화"
    )
    args = parser.parse_args()

    # ── 설정 로드 ─────────────────────────────────────────────────────────
    if not os.path.exists(args.config):
        print(f"[main] 설정 파일을 찾을 수 없습니다: {args.config}", file=sys.stderr)
        sys.exit(1)

    with open(args.config, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if args.out_dir:
        config["output_dir"] = args.out_dir
        config["figures_dir"] = os.path.join(args.out_dir, "figures")
        config["cache_file"] = os.path.join(args.out_dir, "translated_blocks.json")

    output_dir = config.get("output_dir", "output")
    os.makedirs(output_dir, exist_ok=True)

    paper_json_path = os.path.join(output_dir, "paper.json")

    # ── 새 논문 감지: 이전 논문과 PDF 이름이 다르면 output 자동 초기화 ──────
    if not args.skip_extract:
        current_pdf_name = os.path.basename(args.pdf)
        prev_pdf_name = None

        if os.path.exists(paper_json_path):
            try:
                with open(paper_json_path, encoding="utf-8") as f:
                    prev_meta = json.load(f).get("metadata", {})
                prev_pdf_name = os.path.basename(
                    prev_meta.get("source_pdf", "")
                )
            except (json.JSONDecodeError, OSError):
                pass

        if prev_pdf_name and prev_pdf_name != current_pdf_name:
            print(f"[main] 새 논문 감지 ({prev_pdf_name} → {current_pdf_name})")
            print("[main] output 초기화 중...")
            import glob as _glob, shutil as _shutil
            # 중간 파일 삭제
            for f in ["paper.json", "translated.json", "translated_blocks.json"]:
                p = os.path.join(output_dir, f)
                if os.path.exists(p):
                    os.remove(p)
            # 이전 논문 생성 파일 삭제 (PDF + LaTeX 보조 파일)
            prev_stem = os.path.splitext(prev_pdf_name)[0]
            for ext in ("*.pdf", "*.tex", "*.aux", "*.log", "*.out", "*.bib"):
                for p in _glob.glob(os.path.join(output_dir, f"{prev_stem}*{ext.lstrip('*')}")):
                    os.remove(p)
                    print(f"[main] 삭제: {p}")
            # figures 디렉토리 초기화
            figures_dir = config.get("figures_dir", os.path.join(output_dir, "figures"))
            if os.path.isdir(figures_dir):
                _shutil.rmtree(figures_dir)
            os.makedirs(figures_dir, exist_ok=True)

    # ── 수동 캐시 초기화 (--clear-cache) ──────────────────────────────────
    if args.clear_cache:
        cache_file = config.get("cache_file", os.path.join(output_dir, "translated_blocks.json"))
        if os.path.exists(cache_file):
            os.remove(cache_file)
            print(f"[main] 캐시 초기화: {cache_file}")
        else:
            print("[main] 캐시 파일 없음 — 건너뜀")
    translated_json_path = os.path.join(output_dir, "translated.json")

    # ── 1단계: 추출 ───────────────────────────────────────────────────────
    if args.skip_extract and os.path.exists(paper_json_path):
        print(f"[1/3] 추출 건너뜀 — 캐시 사용: {paper_json_path}")
        with open(paper_json_path, encoding="utf-8") as f:
            paper = json.load(f)
    else:
        print("[1/3] 추출 중...")
        from extractor import extract
        paper = extract(args.pdf, config)
        with open(paper_json_path, "w", encoding="utf-8") as f:
            json.dump(paper, f, ensure_ascii=False, indent=2)
        print(
            f"      ✓ {paper['metadata']['pages']}페이지, "
            f"{len(paper['blocks'])}블록, "
            f"{len(paper['figures'])}개 그림 감지"
        )
        print(f"      → {paper_json_path}")

    # ── 2단계: 번역 ───────────────────────────────────────────────────────
    if args.skip_translate and os.path.exists(translated_json_path):
        print(f"[2/3] 번역 건너뜀 — 캐시 사용: {translated_json_path}")
        with open(translated_json_path, encoding="utf-8") as f:
            translated = json.load(f)
    else:
        print("[2/3] 번역 중...")
        from translator import translate
        translated = translate(paper, config)
        with open(translated_json_path, "w", encoding="utf-8") as f:
            json.dump(translated, f, ensure_ascii=False, indent=2)
        translated_count = sum(
            1 for b in translated["blocks"]
            if b.get("translated_text") and b["type"] not in ("equation", "reference")
        )
        print(f"      ✓ {translated_count}블록 번역 완료")
        print(f"      → {translated_json_path}")

    # ── 3단계: 조립 ───────────────────────────────────────────────────────
    print("[3/3] 조립 중...")
    from composer import compose
    pdf_path = compose(translated, config)

    # 원본 PDF를 output 폴더에 복사 (Gemini 품질 검사용)
    import shutil as _shutil
    orig_copy = os.path.join(output_dir, os.path.basename(args.pdf))
    if os.path.abspath(args.pdf) != os.path.abspath(orig_copy):
        _shutil.copy2(args.pdf, orig_copy)

    print(f"\n완료 → {pdf_path}")


if __name__ == "__main__":
    main()
