import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from google import genai
from google.genai import types


SKIP_TYPES = {"reference"}

_EQUATION_SYSTEM_PROMPT = (
    "You are an expert at converting raw math text extracted from PDF into valid LaTeX math.\n"
    "Rules:\n"
    "- Return ONLY the LaTeX math content, NO equation environment wrappers (no \\begin{equation}, no $$)\n"
    "- Convert subscripts: symbol followed by letter/number → use _{} (e.g. θ s → \\theta_s, C_i → C_{i})\n"
    "- Convert superscripts: use ^{} (e.g. a† → a^{\\dagger})\n"
    "- Convert fractions expressed as two lines (numerator / denominator) → \\frac{num}{den}\n"
    "- Convert Unicode math symbols: ρ→\\rho, ε→\\epsilon, θ→\\theta, χ→\\chi, †→\\dagger, ⊥→\\perp, "
    "−→-, ≈→\\approx, √x→\\sqrt{x} (IMPORTANT: preserve the radicand, NEVER output empty \\sqrt{}), "
    "∈→\\in, ≤→\\leq, ≥→\\geq, ∑→\\sum, ∫→\\int\n"
    "- Keep equation numbering like (1), (2) as-is at the end\n"
    "- If the input already looks like valid LaTeX math, clean it up and return\n"
    "- Return ONLY LaTeX code, no explanation or commentary"
)


def should_skip_translation(block: dict) -> bool:
    """번역을 건너뛰어야 하는 블록인지 확인한다."""
    return block.get("type") in SKIP_TYPES


def build_system_prompt(config: dict) -> str:
    """번역 시스템 프롬프트를 구성한다."""
    rules_text = "\n".join(f"- {rule}" for rule in config.get("rules", []))
    style = config.get("translation", {}).get("style", "존댓말 (합니다체)")
    return (
        "당신은 영어 논문을 한국어로 번역하는 전문 번역가입니다.\n"
        f"번역 스타일: {style}\n"
        f"번역 규칙:\n{rules_text}\n"
        "【절대 금지】원문에 없는 내용을 절대 추가하지 마세요. "
        "다른 논문의 내용, 배경 지식, 설명, 예시를 임의로 삽입하는 것은 엄격히 금지됩니다. "
        "오직 주어진 텍스트만 번역하세요.\n"
        "번역할 텍스트만 출력하고, 설명이나 주석은 추가하지 마세요."
    )


def protect_equations(text: str) -> tuple:
    """수식을 플레이스홀더로 치환한다."""
    placeholders = {}
    counter = [0]

    def replace_match(match):
        key = f"__EQ{counter[0]}__"
        placeholders[key] = match.group(0)
        counter[0] += 1
        return key

    text = re.sub(r'\$\$.*?\$\$', replace_match, text, flags=re.DOTALL)
    text = re.sub(
        r'\\begin\{equation\}.*?\\end\{equation\}',
        replace_match, text, flags=re.DOTALL
    )
    text = re.sub(r'\$[^$\n]+?\$', replace_match, text)
    return text, placeholders


def restore_equations(text: str, placeholders: dict) -> str:
    """플레이스홀더를 원래 수식으로 복원한다."""
    for key, value in placeholders.items():
        text = text.replace(key, value)
    return text


def convert_equation_latex(text: str, client, model_name: str, max_retries: int = 3) -> str:
    """PDF에서 추출한 수식 텍스트를 Gemini를 통해 올바른 LaTeX 수식으로 변환한다."""
    if not text.strip():
        return text

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=f"Convert to LaTeX math:\n{text}",
                config=types.GenerateContentConfig(
                    system_instruction=_EQUATION_SYSTEM_PROMPT,
                ),
            )
            result = response.text.strip()
            # 혹시 Gemini가 래퍼를 붙였으면 제거
            result = re.sub(r'^\\begin\{equation\*?\}\s*', '', result)
            result = re.sub(r'\s*\\end\{equation\*?\}$', '', result)
            result = result.strip('$').strip()
            return result
        except Exception as e:
            err_str = str(e)
            if "404" in err_str or "400" in err_str or "NOT_FOUND" in err_str or "INVALID_ARGUMENT" in err_str:
                print(f"[translator] 수식 변환 불가 오류, 원문 반환: {e}", file=sys.stderr)
                return text
            m = re.search(r'retry in (\d+(?:\.\d+)?)\s*s', err_str, re.IGNORECASE)
            suggested = float(m.group(1)) if m else None
            if attempt < max_retries - 1:
                wait = (suggested + 2) if suggested is not None else 30 * (attempt + 1)
                time.sleep(wait)
            else:
                print(f"[translator] 수식 변환 최종 실패, 원문 반환: {e}", file=sys.stderr)
                return text
    return text


def translate_single(text: str, system_prompt: str, client, model_name: str, max_retries: int = 3) -> str:
    """단일 텍스트를 Gemini API로 번역한다. 실패 시 최대 max_retries회 재시도 (지수 백오프)."""
    if max_retries < 1:
        return text

    protected, placeholders = protect_equations(text)
    prompt = f"번역할 텍스트:\n{protected}"

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                ),
            )
            translated = response.text.strip()
            # 결과 길이 검증: 원문 대비 3배 초과 시 환각 가능성 경고 후 재시도
            if len(protected) > 50 and len(translated) > len(protected) * 3:
                print(
                    f"[translator] 경고: 번역 결과가 원문의 {len(translated)/len(protected):.1f}배 — "
                    f"환각 의심, 재시도 ({attempt+1}/{max_retries})",
                    file=sys.stderr,
                )
                if attempt < max_retries - 1:
                    continue
                # 마지막 시도에서도 길면 원문 반환
                print("[translator] 환각 의심 번역 폐기, 원문 반환", file=sys.stderr)
                return text
            return restore_equations(translated, placeholders)
        except Exception as e:
            err_str = str(e)
            # 재시도 불가 오류 (404, 400 등) — 즉시 반환
            if "404" in err_str or "400" in err_str or "NOT_FOUND" in err_str or "INVALID_ARGUMENT" in err_str:
                print(f"[translator] 재시도 불가 오류, 원문 반환: {e}", file=sys.stderr)
                return text

            # API가 알려준 대기 시간 파싱 (예: "Please retry in 31.2s")
            m = re.search(r'retry in (\d+(?:\.\d+)?)\s*s', err_str, re.IGNORECASE)
            suggested = float(m.group(1)) if m else None

            if attempt < max_retries - 1:
                if suggested is not None:
                    wait = suggested + 2
                else:
                    wait = 30 * (attempt + 1)
                print(
                    f"[translator] API 호출 실패 (시도 {attempt + 1}/{max_retries}), "
                    f"{wait:.0f}초 후 재시도: {e}",
                    file=sys.stderr,
                )
                time.sleep(wait)
            else:
                print(f"[translator] API 호출 최종 실패, 원문 반환: {e}", file=sys.stderr)
                return text

    return text


def translate_blocks(
    blocks: list,
    config: dict,
    output_dir: str,
    progress_callback=None,
    stop_event=None,
    max_workers: int = 10,
) -> list:
    """블록 목록을 병렬로 번역한다. 캐시 활용, 진행 상황 콜백 지원."""
    api_key = config.get("api", {}).get("key", "")
    if not api_key:
        raise ValueError("API 키가 설정되지 않았습니다. 설정 탭에서 Gemini API 키를 입력하세요.")

    client = genai.Client(api_key=api_key)
    model_name = config.get("api", {}).get("model", "gemini-2.5-flash")

    system_prompt = build_system_prompt(config)
    cache = load_translation_cache(output_dir)
    cache_lock = threading.Lock()

    total = len(blocks)
    completed_count = 0
    count_lock = threading.Lock()
    results = [None] * total

    def translate_one(i: int, block: dict):
        nonlocal completed_count

        if stop_event and stop_event.is_set():
            raise InterruptedError("번역 중단 요청")

        translated_block = block.copy()

        if should_skip_translation(block):
            translated_block["translated_text"] = block["text"]
        else:
            block_id = block["id"]
            with cache_lock:
                cached = cache.get(block_id)

            if cached:  # 빈 문자열이면 재번역
                translated_block["translated_text"] = cached
            else:
                if block["type"] == "equation":
                    translated_text = convert_equation_latex(block["text"], client, model_name)
                else:
                    translated_text = translate_single(block["text"], system_prompt, client, model_name)
                with cache_lock:
                    cache[block_id] = translated_text
                    save_translation_cache(cache, output_dir)
                translated_block["translated_text"] = translated_text

        results[i] = translated_block

        with count_lock:
            completed_count += 1
            done = completed_count
        if progress_callback:
            progress_callback(done, total, f"번역 중 ({done}/{total} 블록)...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(translate_one, i, block): i for i, block in enumerate(blocks)}
        for future in as_completed(futures):
            if stop_event and stop_event.is_set():
                executor.shutdown(wait=False, cancel_futures=True)
                raise InterruptedError("번역 중단 요청")
            exc = future.exception()
            if exc and isinstance(exc, InterruptedError):
                executor.shutdown(wait=False, cancel_futures=True)
                raise exc

    return results


def load_translation_cache(output_dir: str) -> dict:
    """번역 캐시를 로드한다. 없으면 빈 dict 반환."""
    cache_path = os.path.join(output_dir, "cache", "translated_blocks.json")
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"[translator] 캐시 파일 손상, 초기화합니다: {e}", file=sys.stderr)
        return {}


def save_translation_cache(cache: dict, output_dir: str) -> None:
    """번역 캐시를 저장한다."""
    cache_dir = os.path.join(output_dir, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, "translated_blocks.json")
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def save_translated_blocks(blocks: list, output_dir: str) -> str:
    """번역된 전체 블록 목록을 저장한다."""
    cache_dir = os.path.join(output_dir, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, "translated_blocks_full.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(blocks, f, ensure_ascii=False, indent=2)
    return path
