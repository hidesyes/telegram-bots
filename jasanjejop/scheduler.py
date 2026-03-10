import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from db import delete_old_articles, delete_articles_before, add_article, get_all_articles
from scraper import get_channel_article_urls, scrape_article
from ai import analyze_and_update_style
from config import JASANJEJOP_CHANNEL_URL, ALLOWED_USER_ID

logger = logging.getLogger(__name__)

START_DATE = datetime(2025, 11, 1)

# bot.py에서 주입
_bot_app = None


def setup_scheduler(app) -> AsyncIOScheduler:
    global _bot_app
    _bot_app = app

    scheduler = AsyncIOScheduler()

    # 매일 새벽 3시: 오래된 글 자동 삭제
    scheduler.add_job(
        run_cleanup,
        trigger="cron",
        hour=3,
        minute=0,
        id="cleanup_old_articles"
    )

    # 매일 오전 8시: 자산제곱 새 글 자동 수집
    if JASANJEJOP_CHANNEL_URL:
        scheduler.add_job(
            run_auto_collect,
            trigger="cron",
            hour=8,
            minute=0,
            id="auto_collect_articles"
        )
        logger.info("자동 글 수집 스케줄러 등록 완료 (매일 오전 8시)")

    return scheduler


async def _notify(text: str):
    """ALLOWED_USER_ID에게 텔레그램 메시지 전송"""
    if _bot_app and ALLOWED_USER_ID:
        try:
            await _bot_app.bot.send_message(chat_id=ALLOWED_USER_ID, text=text)
        except Exception as e:
            logger.error(f"[알림 전송 실패] {e}")


async def run_cleanup():
    deleted_old = delete_old_articles()
    deleted_cutoff = delete_articles_before("2025-11-01")
    total = deleted_old + deleted_cutoff
    if total > 0:
        logger.info(f"[자동 삭제] {total}개 글 삭제됨")


async def run_auto_collect():
    """채널에서 새 글 자동 수집 — 로그인 필요 시 텔레그램 알림"""
    logger.info("[자동 수집] 자산제곱 채널 확인 중...")

    try:
        existing = get_all_articles()
        existing_urls = {a["metadata"].get("url", "") for a in existing}

        urls = await get_channel_article_urls(JASANJEJOP_CHANNEL_URL)

        if not urls:
            logger.warning("[자동 수집] URL 수집 실패 또는 결과 없음")
            return

        new_count = 0
        login_required = False

        for url in urls:
            if url in existing_urls:
                continue

            article = await scrape_article(url)

            if "error" in article:
                if article["error"] == "login_required":
                    login_required = True
                    break
                logger.warning(f"[자동 수집] 스크래핑 실패: {url} - {article['error']}")
                continue

            # 2025-11-01 이전 글 건너뜀
            try:
                written_date = datetime.fromisoformat(article["written_date"])
                if written_date < START_DATE:
                    continue
            except ValueError:
                pass

            analyze_and_update_style(article["content"])
            result = add_article(article)
            if result not in ("skipped", "too_old"):
                new_count += 1
                logger.info(f"[자동 수집] 새 글 저장: {article['title']}")
            await asyncio.sleep(2)

        if login_required:
            logger.warning("[자동 수집] 로그인 필요 — 쿠키 만료")
            await _notify(
                "⚠️ [자동 수집 실패]\n"
                "네이버 로그인이 만료됐어요.\n"
                "/login 명령어로 다시 로그인해주세요!"
            )
        elif new_count > 0:
            await _notify(f"✅ 새 글 {new_count}개가 자동으로 저장됐어요!")
            logger.info(f"[자동 수집] 완료 — 새 글 {new_count}개 추가됨")
        else:
            logger.info("[자동 수집] 새 글 없음")

    except Exception as e:
        logger.error(f"[자동 수집] 오류: {e}")
        await _notify(f"❌ [자동 수집 오류]\n{e}")
