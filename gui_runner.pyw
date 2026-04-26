"""
gui_runner.pyw — Physics-Trans v2.0 더블클릭 실행 진입점
.pyw 확장자: Windows에서 콘솔 창 없이 실행됨
"""
import sys
import os

# 이 파일이 있는 폴더를 sys.path에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui import run

run()
