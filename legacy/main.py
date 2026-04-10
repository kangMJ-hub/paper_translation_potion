import os
import sys
import tkinter as tk

import yaml

from gui import PaperTranslatorGUI


CONFIG_FILENAME = "config.yaml"


def load_config(config_path: str) -> dict:
    """config.yaml을 로드한다. 없으면 기본값 반환."""
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {
        "api": {"key": "", "model": "gemini-2.5-flash"},
        "translation": {
            "source_language": "English",
            "target_language": "Korean",
            "style": "존댓말 (합니다체)",
        },
        "rules": [
            "수식은 번역하지 않고 LaTeX 코드 그대로 유지한다.",
            "물리학 전문 용어는 가능하면 한국어로 번역하되, 혼동 우려가 있으면 영어 병기한다.",
            "논문의 학술적 문체를 유지한다.",
            "저자명, 기관명, 고유명사는 번역하지 않는다.",
            "그림 캡션과 표 캡션도 번역한다.",
            "참고문헌 항목은 번역하지 않고 원문 그대로 유지한다.",
        ],
        "latex": {
            "documentclass": "article",
            "font_main": "NanumMyeongjo",
            "font_sans": "NanumGothic",
        },
    }


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, CONFIG_FILENAME)
    config = load_config(config_path)

    root = tk.Tk()
    app = PaperTranslatorGUI(root, config, config_path)
    root.mainloop()


if __name__ == "__main__":
    main()
