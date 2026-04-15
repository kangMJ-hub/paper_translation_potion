"""
download_papers.py — arXiv API로 분야별 10페이지 이하 논문 PDF 20편씩 다운로드
저장 경로: tests/papers/{category}/
사용법: python download_papers.py
"""

import os
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import fitz  # PyMuPDF — 정확한 페이지 수 측정

CATEGORIES = ["quant-ph", "cond-mat", "hep-ph", "nucl-th", "astro-ph"]
PAPERS_PER_CAT = 20
MAX_PAGES = 10
SAVE_DIR = "tests/papers"
ARXIV_API = "https://export.arxiv.org/api/query"

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}




def fetch_entries(category: str, start: int, max_results: int) -> list[dict]:
    """arXiv API에서 논문 목록을 가져온다."""
    params = urllib.parse.urlencode({
        "search_query": f"cat:{category}",
        "start": start,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    url = f"{ARXIV_API}?{params}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    entries = []
    for entry in root.findall("atom:entry", NS):
        arxiv_id_raw = entry.findtext("atom:id", "", NS).strip()
        # ID에서 순수 arxiv ID 추출
        arxiv_id = arxiv_id_raw.split("/abs/")[-1].replace("/", "_")

        title = entry.findtext("atom:title", "", NS).strip().replace("\n", " ")

        # PDF 링크 찾기
        pdf_url = None
        for link in entry.findall("atom:link", NS):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "").replace("http://", "https://")
                if not pdf_url.endswith(".pdf"):
                    pdf_url += ".pdf"
                break
        if not pdf_url:
            continue

        entries.append({
            "id": arxiv_id,
            "title": title,
            "pdf_url": pdf_url,
        })
    return entries


def download_pdf(pdf_url: str, save_path: str) -> bool:
    """PDF를 다운로드한다. 성공 시 True."""
    try:
        req = urllib.request.Request(
            pdf_url,
            headers={"User-Agent": "Mozilla/5.0 (research downloader)"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        if len(data) < 1000:
            return False
        with open(save_path, "wb") as f:
            f.write(data)
        return True
    except Exception as e:
        print(f"    다운로드 실패: {e}")
        return False


def get_page_count_from_file(pdf_path: str) -> int:
    """PyMuPDF로 PDF 파일의 정확한 페이지 수를 반환한다."""
    try:
        doc = fitz.open(pdf_path)
        pages = doc.page_count
        doc.close()
        return pages
    except Exception:
        return 0


def download_category(category: str) -> None:
    cat_dir = os.path.join(SAVE_DIR, category)
    os.makedirs(cat_dir, exist_ok=True)

    downloaded = 0
    start = 0
    batch = 50  # 한 번에 가져올 후보 수

    print(f"\n[{category}] 다운로드 시작 (목표: {PAPERS_PER_CAT}편, 최대 {MAX_PAGES}페이지)")

    while downloaded < PAPERS_PER_CAT:
        print(f"  API 조회: start={start}, batch={batch}")
        try:
            entries = fetch_entries(category, start, batch)
        except Exception as e:
            print(f"  API 오류: {e}")
            time.sleep(5)
            continue

        if not entries:
            print("  더 이상 논문 없음.")
            break

        for entry in entries:
            if downloaded >= PAPERS_PER_CAT:
                break

            arxiv_id = entry["id"]
            pdf_url  = entry["pdf_url"]
            title    = entry["title"][:60]

            # 이미 다운로드된 파일 건너뜀
            save_path = os.path.join(cat_dir, f"{arxiv_id}.pdf")
            if os.path.exists(save_path):
                pages = get_page_count_from_file(save_path)
                if pages <= MAX_PAGES:
                    downloaded += 1
                continue

            # 임시 다운로드
            tmp_path = save_path + ".tmp"
            print(f"  [{downloaded+1}/{PAPERS_PER_CAT}] {arxiv_id} | {title}")
            ok = download_pdf(pdf_url, tmp_path)
            if not ok:
                time.sleep(2)
                continue

            # 페이지 수 확인
            pages = get_page_count_from_file(tmp_path)
            if pages == 0:
                # 페이지 수 불명 → 통과 (짧은 논문일 가능성)
                print(f"    페이지 수 불명 → 통과")
                os.rename(tmp_path, save_path)
                downloaded += 1
            elif pages <= MAX_PAGES:
                print(f"    {pages}페이지 → 저장")
                os.rename(tmp_path, save_path)
                downloaded += 1
            else:
                print(f"    {pages}페이지 → 건너뜀 (>{MAX_PAGES})")
                os.remove(tmp_path)

            time.sleep(1)  # arXiv rate limit 준수

        start += batch
        time.sleep(3)

    print(f"[{category}] 완료: {downloaded}편 저장 → {cat_dir}")


def main():
    os.makedirs(SAVE_DIR, exist_ok=True)
    total = 0
    for cat in CATEGORIES:
        download_category(cat)
        existing = len([f for f in os.listdir(os.path.join(SAVE_DIR, cat)) if f.endswith(".pdf")])
        total += existing
        time.sleep(3)

    print(f"\n전체 완료: {total}편 다운로드됨 → {SAVE_DIR}/")


if __name__ == "__main__":
    main()
