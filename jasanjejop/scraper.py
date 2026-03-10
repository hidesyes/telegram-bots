import json
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright
from config import COOKIES_PATH


async def load_cookies():
    try:
        with open(COOKIES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


async def save_cookies(cookies):
    with open(COOKIES_PATH, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)


async def do_browser_login():
    """브라우저 열어서 수동 로그인 후 쿠키 저장"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto("https://nid.naver.com/nidlogin.login")
        print("브라우저에서 네이버 로그인을 완료해주세요. 로그인 후 자동으로 쿠키가 저장됩니다.")

        # 로그인 완료될 때까지 대기 (로그인 페이지에서 벗어나면 완료)
        for _ in range(180):
            await asyncio.sleep(1)
            current = page.url
            if "nidlogin" not in current and "naver.com" in current:
                break
        await asyncio.sleep(2)

        cookies = await context.cookies()
        await save_cookies(cookies)
        await browser.close()
        return True


async def scrape_article(url: str) -> dict:
    """네이버 프리미엄 콘텐츠 스크래핑 (API 응답 인터셉트로 날짜 정확 추출)"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        cookies = await load_cookies()
        if cookies:
            await context.add_cookies(cookies)

        page = await context.new_page()

        # API 응답에서 날짜 캡처
        api_date = {"value": None}

        async def capture_date(response):
            try:
                if "api" in response.url and ("content" in response.url or "article" in response.url):
                    body = await response.json()
                    # 다양한 API 응답 구조 탐색
                    for key in ["publishDate", "regDate", "createDate", "date", "pubDate", "publishedAt"]:
                        val = _deep_find(body, key)
                        if val:
                            api_date["value"] = str(val)
                            break
            except Exception:
                pass

        page.on("response", capture_date)

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            current_url = page.url
            if "login" in current_url or "nidlogin" in current_url:
                await browser.close()
                return {"error": "login_required"}

            # 제목 추출
            title = await page.evaluate("""
                () => {
                    const selectors = [
                        'h2.ArticleContent_title__SiCNe',
                        'h2[class*="title"]',
                        'h1[class*="title"]',
                        '.article_title',
                        'h1', 'h2'
                    ];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el && el.textContent.trim()) return el.textContent.trim();
                    }
                    return document.title;
                }
            """)

            # 날짜 추출 (우선순위: API > JSON-LD > meta > DOM > URL)
            date_text = api_date["value"]

            if not date_text:
                date_text = await page.evaluate(r"""
                    () => {
                        // 1. JSON-LD 구조화 데이터
                        const jsonld = document.querySelector('script[type="application/ld+json"]');
                        if (jsonld) {
                            try {
                                const data = JSON.parse(jsonld.textContent);
                                if (data.datePublished) return data.datePublished;
                                if (data.dateCreated) return data.dateCreated;
                            } catch(e) {}
                        }
                        // 2. meta 태그
                        const metas = [
                            'meta[property="article:published_time"]',
                            'meta[name="pubdate"]',
                            'meta[name="date"]',
                            'meta[property="og:updated_time"]'
                        ];
                        for (const sel of metas) {
                            const el = document.querySelector(sel);
                            if (el) return el.getAttribute('content');
                        }
                        // 3. time 태그
                        const time = document.querySelector('time');
                        if (time) return time.getAttribute('datetime') || time.textContent.trim();
                        // 4. 날짜 관련 클래스
                        const dateEls = document.querySelectorAll('[class*="date"],[class*="Date"],[class*="time"],[class*="Time"]');
                        for (const el of dateEls) {
                            const txt = el.textContent.trim();
                            if (/20\d{2}/.test(txt)) return txt;
                        }
                        return null;
                    }
                """)

            # URL에서 날짜 추출 시도 (최후 수단)
            if not date_text:
                import re
                match = re.search(r'(20\d{2})[.\-/]?(\d{2})[.\-/]?(\d{2})', url)
                if match:
                    date_text = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"

            # 본문 추출
            content = await page.evaluate("""
                () => {
                    const selectors = [
                        '.ArticleContent_article__Pc8dB',
                        '[class*="article__"]',
                        '[class*="ArticleContent"]',
                        '.article_content',
                        'article',
                        '.content_area',
                        '[class*="content"]'
                    ];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el && el.textContent.trim().length > 100) {
                            return el.textContent.trim();
                        }
                    }
                    return document.body.innerText;
                }
            """)

            written_date = parse_date(date_text)
            await browser.close()

            return {
                "title": title,
                "content": content,
                "url": url,
                "written_date": written_date.isoformat(),
                "scraped_date": datetime.now().isoformat()
            }

        except Exception as e:
            await browser.close()
            return {"error": str(e)}


def _deep_find(obj, key: str):
    """중첩된 JSON에서 특정 키 찾기"""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            result = _deep_find(v, key)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _deep_find(item, key)
            if result:
                return result
    return None


async def get_channel_article_urls(channel_url: str) -> list:
    """채널 페이지에서 최신 글 URL 목록 수집"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        cookies = await load_cookies()
        if cookies:
            await context.add_cookies(cookies)

        page = await context.new_page()

        try:
            await page.goto(channel_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            urls = await page.evaluate("""
                () => {
                    const links = document.querySelectorAll('a[href*="/contents/"]');
                    const found = new Set();
                    links.forEach(a => {
                        const href = a.href;
                        if (href && href.includes('contents.premium.naver.com')) {
                            found.add(href);
                        }
                    });
                    return Array.from(found).slice(0, 20);
                }
            """)

            await browser.close()
            return urls

        except Exception as e:
            await browser.close()
            print(f"채널 수집 오류: {e}")
            return []


def parse_date(date_text: str) -> datetime:
    """날짜 텍스트 → datetime 변환"""
    if not date_text:
        return datetime.now()

    date_text = date_text.strip()

    # ISO 형식 (타임존 포함 포함) 우선 시도
    try:
        # +09:00 같은 타임존 제거 후 파싱
        import re as _re
        clean = _re.sub(r'[+-]\d{2}:\d{2}$', '', date_text)
        return datetime.fromisoformat(clean)
    except ValueError:
        pass

    formats = [
        "%Y.%m.%d %H:%M:%S",
        "%Y.%m.%d %H:%M",
        "%Y.%m.%d.",
        "%Y.%m.%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_text, fmt)
        except ValueError:
            continue

    # 날짜 부분만 추출 시도 (앞 10자리 YYYY-MM-DD 또는 YYYY.MM.DD)
    import re as _re
    match = _re.search(r'(20\d{2})[.\-/](\d{2})[.\-/](\d{2})', date_text)
    if match:
        try:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass

    return datetime.now()
