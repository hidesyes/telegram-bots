"""
자산제곱 채널 글 일괄 수집 스크립트
사용법: py bulk_collect.py
"""
import asyncio
import json
import sys
from datetime import datetime
from playwright.async_api import async_playwright
from config import COOKIES_PATH, JASANJEJOP_CHANNEL_URL
from db import add_article, get_all_articles, get_count, clear_all_articles
from ai import analyze_and_update_style
from scraper import scrape_article, parse_date

START_DATE = datetime(2025, 11, 1)  # 2025년 11월 이후 글만 수집


async def load_cookies():
    try:
        with open(COOKIES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


async def get_all_article_urls(channel_url: str) -> list:
    """채널 페이지를 스크롤하며 모든 글 URL 수집"""
    print("채널 페이지 접속 중...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        cookies = await load_cookies()
        if cookies:
            await context.add_cookies(cookies)
        else:
            print("[오류] 로그인 쿠키가 없어요. 봇에서 /login 먼저 해주세요.")
            await browser.close()
            return []

        page = await context.new_page()

        try:
            await page.goto(channel_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            all_urls = set()
            prev_count = 0
            scroll_attempts = 0
            max_scrolls = 50  # 최대 50번 스크롤

            print("글 목록 수집 중 (스크롤)...")

            while scroll_attempts < max_scrolls:
                # 현재 페이지의 글 링크 수집
                urls = await page.evaluate("""
                    () => {
                        const links = document.querySelectorAll('a[href*="/contents/"]');
                        const found = new Set();
                        links.forEach(a => {
                            if (a.href && a.href.includes('contents.premium.naver.com')) {
                                found.add(a.href);
                            }
                        });
                        return Array.from(found);
                    }
                """)

                for url in urls:
                    all_urls.add(url)

                print(f"  수집된 글: {len(all_urls)}개", end="\r")

                # 더 이상 새 글이 없으면 종료
                if len(all_urls) == prev_count and scroll_attempts > 3:
                    break

                prev_count = len(all_urls)

                # 페이지 스크롤
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(2)

                # "더보기" 버튼 클릭 시도
                try:
                    more_btn = page.locator('button:has-text("더보기"), button:has-text("더 보기"), [class*="more"]').first
                    if await more_btn.is_visible():
                        await more_btn.click()
                        await asyncio.sleep(2)
                except:
                    pass

                scroll_attempts += 1

            print(f"\n총 {len(all_urls)}개 글 URL 수집 완료")
            await browser.close()
            return list(all_urls)

        except Exception as e:
            print(f"❌ 오류: {e}")
            await browser.close()
            return []


async def main():
    reset_mode = "--reset" in sys.argv

    print("=" * 50)
    print("자산제곱 글 일괄 수집 시작")
    print(f"수집 기준: {START_DATE.strftime('%Y년 %m월')} 이후 글")
    if reset_mode:
        print("[초기화 모드] 기존 글 전부 삭제 후 재수집")
    print("=" * 50)

    if not JASANJEJOP_CHANNEL_URL:
        print("❌ 채널 URL이 설정되지 않았어요.")
        return

    # 초기화 모드: 기존 글 전부 삭제
    if reset_mode:
        deleted = clear_all_articles()
        print(f"기존 글 {deleted}개 삭제 완료\n")
        existing_urls = set()
    else:
        existing = get_all_articles()
        existing_urls = {a["metadata"].get("url", "") for a in existing}
        print(f"기존 저장된 글: {len(existing_urls)}개\n")

    # 채널에서 전체 URL 수집
    all_urls = await get_all_article_urls(JASANJEJOP_CHANNEL_URL)

    if not all_urls:
        print("수집된 글이 없어요.")
        return

    # 새 글만 필터링
    new_urls = [u for u in all_urls if u not in existing_urls]
    print(f"새로 수집할 글: {len(new_urls)}개\n")

    if not new_urls:
        print("모두 이미 저장된 글이에요!")
        return

    # 각 글 스크래핑 & 저장
    saved = 0
    skipped = 0
    failed = 0

    for i, url in enumerate(new_urls, 1):
        print(f"[{i}/{len(new_urls)}] 처리 중...")

        article = await scrape_article(url)

        if "error" in article:
            if article["error"] == "login_required":
                print("  [오류] 로그인 필요 -- 봇에서 /login 해주세요.")
                break
            print(f"  [오류] 스크래핑 실패: {article['error']}")
            failed += 1
            continue

        # 날짜 필터링 (2025년 11월 이후만)
        written_date = datetime.fromisoformat(article["written_date"])
        if written_date < START_DATE:
            print(f"  [건너뜀] ({written_date.strftime('%Y-%m-%d')}): {article['title'][:30]}")
            skipped += 1
            continue

        # 스타일 분석 & 저장
        analyze_and_update_style(article["content"])
        result = add_article(article)
        if result == "skipped":
            print(f"  [생략] [{written_date.strftime('%Y-%m-%d')}] {article['title'][:40]} (유사 글 존재)")
            skipped += 1
        else:
            saved += 1
            print(f"  [저장] [{written_date.strftime('%Y-%m-%d')}] {article['title'][:40]}")
        await asyncio.sleep(1)  # 서버 부하 방지

    print("\n" + "=" * 50)
    print(f"완료! 저장: {saved}개 | 건너뜀: {skipped}개 | 실패: {failed}개")
    print(f"총 저장된 글: {get_count()}개")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
