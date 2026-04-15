"""
translator.py — Physics-Trans v2.0
paper.json → translated.json (Vertex AI Gemini)

인증: gcloud auth application-default login
      또는 GOOGLE_APPLICATION_CREDENTIALS 환경변수
"""

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import vertexai
from vertexai.generative_models import GenerativeModel

from utils import fix_gemini_latex, apply_term_dict, protect_equations, restore_equations


# ---------------------------------------------------------------------------
# 블록 타입별 처리 분류
# ---------------------------------------------------------------------------

_SKIP_TYPES = {"reference"}        # 원문 그대로 유지
_EQUATION_TYPES = {"equation"}     # LaTeX 정규화 (번역 아님)


# ---------------------------------------------------------------------------
# 공개 진입점
# ---------------------------------------------------------------------------

def translate(paper: dict, config: dict) -> dict:
    """
    paper.json dict를 받아 각 블록을 번역한 translated.json dict를 반환한다.

    - equation / reference 타입은 원문 유지
    - 캐시 적중 시 API 호출 생략
    - ThreadPoolExecutor로 병렬 처리
    """
    _init_vertex(config)

    model_name = config.get("model", "gemini-3.0-flash")
    max_workers = config.get("max_workers", 5)
    cache_file = config.get("cache_file", "output/translated_blocks.json")

    system_prompt = _build_system_prompt(config.get("translation_style", "합니다체"))
    model = GenerativeModel(
        model_name,
        system_instruction=system_prompt,
    )
    eq_model = GenerativeModel(
        model_name,
        system_instruction=(
            "You are a LaTeX math expert. "
            "Convert equation text extracted from a PDF into valid LaTeX math code. "
            "Output only the LaTeX math content — no surrounding $$, "
            r"\begin{equation}"
            ", or explanation."
        ),
    )
    cache = _load_cache(cache_file)

    blocks = paper.get("blocks", [])
    total = len(blocks)
    results: list[dict | None] = [None] * total

    import threading
    cache_lock = threading.Lock()

    def translate_one(i: int, block: dict) -> None:
        translated_block = block.copy()
        btype = block.get("type", "")

        if btype in _SKIP_TYPES:
            translated_block["translated_text"] = block["text"]
        else:
            block_id = block["id"]
            with cache_lock:
                cached = cache.get(block_id)

            if cached:
                translated_block["translated_text"] = cached
            else:
                if btype in _EQUATION_TYPES:
                    result = _normalize_equation(block, eq_model, config)
                else:
                    result = _translate_block(block, model, config)
                # 번역 실패 캐시 오염 방지:
                # paragraph 계열 블록에서 결과가 원문과 동일하고 한국어가 없으면
                # 캐시에 저장하지 않아 다음 실행 시 재시도하게 한다.
                is_failed = (
                    btype not in _EQUATION_TYPES
                    and result == block["text"]
                    and not re.search(r"[가-힣]", result)
                )
                if not is_failed:
                    with cache_lock:
                        cache[block_id] = result
                        _save_cache(cache, cache_file)
                translated_block["translated_text"] = result

        results[i] = translated_block

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(translate_one, i, block): i
            for i, block in enumerate(blocks)
        }
        completed = 0
        for future in as_completed(futures):
            exc = future.exception()
            if exc:
                print(f"[translator] 블록 번역 중 예외: {exc}", file=sys.stderr)
            completed += 1
            print(f"\r[translator] {completed}/{total} 블록 번역 완료", end="", flush=True)
    print()  # 줄바꿈

    translated = dict(paper)
    translated["blocks"] = results
    return translated


# ---------------------------------------------------------------------------
# 단일 블록 번역
# ---------------------------------------------------------------------------

def _normalize_equation(block: dict, model: GenerativeModel, config: dict) -> str:
    """
    PDF 추출 수식 텍스트를 유효한 LaTeX 수식으로 정규화한다.
    이미 LaTeX인 경우 그대로 반환. 최종 실패 시 원문 반환.
    """
    text = block["text"].strip()
    max_retries = config.get("max_retries", 3)

    # 이미 LaTeX인 경우 정규화 불필요
    if re.search(r"\\[a-zA-Z]+\{", text) or text.startswith(r"\begin"):
        return text

    for attempt in range(max_retries):
        try:
            response = model.generate_content(
                f"Convert this equation to LaTeX math:\n{text}"
            )
            return response.text.strip()
        except Exception as e:
            err_str = str(e)
            if any(code in err_str for code in ("404", "400", "NOT_FOUND", "INVALID_ARGUMENT")):
                return text
            wait = 5 * (attempt + 1)
            if attempt < max_retries - 1:
                time.sleep(wait)
            else:
                return text

    return text


def _translate_block(block: dict, model: GenerativeModel, config: dict) -> str:
    """
    단일 블록을 번역한다.
    1. protect_equations()로 수식을 플레이스홀더로 치환
    2. Vertex AI API 호출 (system_instruction은 model에 이미 설정됨)
    3. restore_equations()로 플레이스홀더를 원래 수식으로 복원
    4. 환각 감지 (길이 3배 초과) → 재시도
    5. fix_gemini_latex(), apply_term_dict() 적용
    6. 최종 실패 시 원문 반환
    """
    text = block["text"]
    max_retries = config.get("max_retries", 3)
    hallucination_ratio = config.get("hallucination_ratio", 3.0)

    protected, eq_map = protect_equations(text)

    for attempt in range(max_retries):
        try:
            response = model.generate_content(f"번역할 텍스트:\n{protected}")
            translated = response.text.strip()
            translated = restore_equations(translated, eq_map)

            # 환각 감지: 길이 3배 초과
            if len(text) > 50 and len(translated) > len(text) * hallucination_ratio:
                print(
                    f"\n[translator] 경고: 환각 의심 "
                    f"({len(translated)/len(text):.1f}배), "
                    f"재시도 ({attempt+1}/{max_retries})",
                    file=sys.stderr,
                )
                if attempt < max_retries - 1:
                    continue
                print("[translator] 환각 의심 번역 폐기, 원문 반환", file=sys.stderr)
                return text

            result = fix_gemini_latex(translated)
            result = apply_term_dict(result)
            return result

        except Exception as e:
            err_str = str(e)
            # 재시도 불가 오류
            if any(code in err_str for code in ("404", "400", "NOT_FOUND", "INVALID_ARGUMENT")):
                print(f"\n[translator] 재시도 불가 오류, 원문 반환: {e}", file=sys.stderr)
                return text

            # API 권장 대기 시간 파싱 ("retry in 31.2s")
            import re
            m = re.search(r"retry in (\d+(?:\.\d+)?)\s*s", err_str, re.IGNORECASE)
            wait = float(m.group(1)) + 2 if m else 30 * (attempt + 1)

            if attempt < max_retries - 1:
                print(
                    f"\n[translator] API 오류 (시도 {attempt+1}/{max_retries}), "
                    f"{wait:.0f}초 후 재시도: {e}",
                    file=sys.stderr,
                )
                time.sleep(wait)
            else:
                print(f"\n[translator] API 최종 실패, 원문 반환: {e}", file=sys.stderr)
                return text

    return text


# ---------------------------------------------------------------------------
# 시스템 프롬프트
# ---------------------------------------------------------------------------

def _build_system_prompt(style: str) -> str:
    """번역 시스템 프롬프트를 생성한다."""
    return (
        "당신은 영어 물리학 논문을 한국어로 번역하는 전문 번역가입니다.\n"
        f"번역 스타일: {style}\n"
        "번역 규칙:\n"
        "- $...$, $$...$$, \\begin{equation}...\\end{equation}, \\begin{align}...\\end{align} 등\n"
        "  LaTeX 수식 환경 안의 내용은 절대 번역하거나 수정하지 않는다.\n"
        "- 수식 기호(\\alpha, \\sigma, \\frac 등 백슬래시로 시작하는 LaTeX 명령어)도 그대로 유지한다.\n"
        "- 물리학 전문 용어는 한국어로 번역하되, 혼동 우려가 있으면 영어 병기한다.\n"
        "- 저자명, 기관명, 고유명사는 번역하지 않는다.\n"
        "- 그림 캡션은 번역하고, Figure는 '그림'으로 표기한다.\n"
        "- 참고문헌은 원문 그대로 유지한다.\n"
        "- 학술적 문체와 한다체를 유지한다.\n"
        "【절대 금지】원문에 없는 내용을 추가하거나 다른 논문 내용을 삽입하지 않는다.\n"
        "번역 결과 텍스트만 출력하고, 설명이나 주석은 추가하지 않는다."
    )


# ---------------------------------------------------------------------------
# Vertex AI 초기화
# ---------------------------------------------------------------------------

def _init_vertex(config: dict) -> None:
    """Vertex AI를 초기화한다. ADC 인증 사용."""
    project_id = config.get("project_id", "")
    location = config.get("location", "us-central1")
    if not project_id:
        raise ValueError(
            "config.yaml에 project_id가 설정되지 않았습니다.\n"
            "config.yaml의 project_id를 GCP 프로젝트 ID로 설정하세요."
        )
    # 한국어 Windows에서 gcloud가 CP949로 출력해 UnicodeDecodeError 발생 방지.
    # generate_content() 첫 호출 시 lazy credential 로딩에도 적용되어야 하므로
    # 패치를 세션 전체에 유지 (finally로 원복하지 않음). 중복 패치 방지.
    import google.auth._cloud_sdk as _cs
    if not getattr(_cs, "_cp949_patched", False):
        _orig = _cs.get_project_id
        def _safe(_orig=_orig, _pid=project_id):
            try:
                return _orig()
            except UnicodeDecodeError:
                return _pid
        _cs.get_project_id = _safe
        _cs._cp949_patched = True
    vertexai.init(project=project_id, location=location)


# ---------------------------------------------------------------------------
# 캐시 로드 / 저장
# ---------------------------------------------------------------------------

def _load_cache(cache_file: str) -> dict:
    """번역 캐시를 로드한다. 파일이 없거나 손상되면 빈 dict 반환."""
    if not os.path.exists(cache_file):
        return {}
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[translator] 캐시 파일 손상, 초기화합니다: {e}", file=sys.stderr)
        return {}


def _save_cache(cache: dict, cache_file: str) -> None:
    """번역 캐시를 저장한다."""
    os.makedirs(os.path.dirname(cache_file) or ".", exist_ok=True)
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# CLI 단독 실행 (테스트용)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import yaml

    if len(sys.argv) < 2:
        print("사용법: python translator.py <paper.json> [config.yaml]")
        sys.exit(1)

    paper_path = sys.argv[1]
    cfg_path = sys.argv[2] if len(sys.argv) > 2 else "config.yaml"

    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    with open(paper_path, encoding="utf-8") as f:
        paper_data = json.load(f)

    result = translate(paper_data, cfg)

    out_dir = cfg.get("output_dir", "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "translated.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[translator] 출력: {out_path}")
