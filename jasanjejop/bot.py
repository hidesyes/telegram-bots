import os
import re
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from config import TELEGRAM_TOKEN, ALLOWED_USER_ID
from scraper import scrape_article, do_browser_login
from db import add_article, search_articles, get_all_articles, get_count, delete_old_articles, delete_articles_before
from ai import analyze_and_update_style, ask_as_jasanjejop, clear_history
from scheduler import setup_scheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r'https?://\S+')


def check_auth(user_id: int) -> bool:
    return user_id == ALLOWED_USER_ID


# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update.effective_user.id):
        return

    await update.message.reply_text(
        "안녕하세요! 자산제곱 분석 봇입니다 📊\n\n"
        "💡 자유롭게 대화하듯 사용하세요!\n\n"
        "🔗 링크 전송 → 자동으로 글 저장 & 분석\n"
        "💬 질문 입력 → 자산제곱 스타일 투자 분석\n"
        "🌐 실시간 뉴스 + 저장된 글 종합 답변\n\n"
        "📌 명령어:\n"
        "/login — 네이버 로그인\n"
        "/list — 저장된 글 목록\n"
        "/status — 현재 상태\n"
        "/clear — 대화 기록 초기화\n"
        "/cleanup — 오래된 글 삭제"
    )


# ─────────────────────────────────────────────
# /login
# ─────────────────────────────────────────────
async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update.effective_user.id):
        return

    await update.message.reply_text(
        "🌐 브라우저가 열립니다.\n"
        "네이버에 로그인 후 잠시 기다려주세요.\n"
        "로그인이 완료되면 자동으로 쿠키가 저장됩니다!"
    )

    try:
        await do_browser_login()
        await update.message.reply_text("✅ 로그인 완료! 이제 링크를 보내면 글을 저장할 수 있어요.")
    except Exception as e:
        await update.message.reply_text(f"❌ 로그인 실패: {e}")


# ─────────────────────────────────────────────
# /list
# ─────────────────────────────────────────────
async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update.effective_user.id):
        return

    articles = get_all_articles()

    if not articles:
        await update.message.reply_text("저장된 글이 없습니다.")
        return

    msg = f"📚 저장된 글 목록 (총 {len(articles)}개):\n\n"
    for i, article in enumerate(articles[:20], 1):
        meta = article["metadata"]
        title = meta.get("title", "제목 없음")[:35]
        date = meta.get("written_date", "")[:10]
        msg += f"{i}. {title}\n   📅 {date}\n"

    if len(articles) > 20:
        msg += f"\n... 외 {len(articles) - 20}개"

    await update.message.reply_text(msg)


# ─────────────────────────────────────────────
# /status
# ─────────────────────────────────────────────
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update.effective_user.id):
        return

    count = get_count()
    has_cookies = os.path.exists("cookies.json")
    has_profile = os.path.exists("style_profile.json")

    await update.message.reply_text(
        f"📊 현재 상태:\n\n"
        f"🔐 네이버 로그인: {'✅ 완료' if has_cookies else '❌ 미완료 (/login 필요)'}\n"
        f"🎭 스타일 프로필: {'✅ 구축됨' if has_profile else '❌ 없음 (글 추가 필요)'}\n"
        f"💾 저장된 글: {count}개\n\n"
        f"📅 6개월 지난 글은 매일 새벽 3시에 자동 삭제됩니다."
    )


# ─────────────────────────────────────────────
# /clear
# ─────────────────────────────────────────────
async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update.effective_user.id):
        return

    clear_history(update.effective_user.id)
    await update.message.reply_text("🗑 대화 기록이 초기화되었습니다. 새로운 대화를 시작하세요!")


# ─────────────────────────────────────────────
# /cleanup
# ─────────────────────────────────────────────
async def cleanup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update.effective_user.id):
        return

    deleted_old = delete_old_articles()
    deleted_cutoff = delete_articles_before("2025-11-01")
    total = deleted_old + deleted_cutoff

    if total > 0:
        msg = f"🗑 총 {total}개 글 삭제 완료!\n"
        if deleted_cutoff > 0:
            msg += f"  • 2025-11-01 이전 글: {deleted_cutoff}개\n"
        if deleted_old > 0:
            msg += f"  • 6개월 이상 지난 글: {deleted_old}개\n"
        msg += f"💾 남은 글: {get_count()}개"
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text("삭제할 글이 없어요. (모두 2025-11-01 이후, 6개월 이내)")


# ─────────────────────────────────────────────
# 일반 메시지 처리 (링크 or 질문 자동 감지)
# ─────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update.effective_user.id):
        return

    text = update.message.text.strip()
    user_id = update.effective_user.id
    urls = URL_PATTERN.findall(text)

    if urls:
        # 링크 감지 → 자동 글 추가
        url = urls[0]
        await update.message.reply_text("🔍 글을 읽어오는 중입니다...")

        article = await scrape_article(url)

        if "error" in article:
            if article["error"] == "login_required":
                await update.message.reply_text(
                    "❌ 로그인이 필요합니다.\n/login 명령어로 먼저 로그인해주세요."
                )
            else:
                await update.message.reply_text(
                    f"❌ 글을 가져오지 못했어요.\n오류: {article['error']}"
                )
            return

        await update.message.reply_text(
            f"📄 글 수집 완료!\n제목: {article['title']}\n\n💭 스타일 분석 중..."
        )

        analyze_and_update_style(article["content"])
        result = add_article(article)

        if result == "too_old":
            await update.message.reply_text(
                f"⏭️ 저장 생략!\n"
                f"📝 2025년 11월 1일 이전 글은 저장하지 않아요."
            )
        elif result == "skipped":
            await update.message.reply_text(
                f"⏭️ 저장 생략!\n"
                f"📝 제목: {article['title']}\n"
                f"비슷한 최신 글이 이미 저장되어 있어서 저장하지 않았어요.\n"
                f"💾 총 {get_count()}개 글 저장됨"
            )
        else:
            await update.message.reply_text(
                f"✅ 저장 완료!\n"
                f"📝 제목: {article['title']}\n"
                f"📅 작성일: {article['written_date'][:10]}\n"
                f"💾 총 {get_count()}개 글 저장됨"
            )

    else:
        # 일반 텍스트 → 자산제곱 스타일 답변 (실시간 검색 + 대화 맥락)
        await update.message.reply_text("💭 분석 중입니다. 잠시만 기다려주세요...")

        related = search_articles(text, n_results=3) if get_count() > 0 else []
        answer = ask_as_jasanjejop(text, related, user_id=user_id)

        await update.message.reply_text(answer)


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("cleanup", cleanup_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = setup_scheduler(app)
    scheduler.start()

    print("자산제곱 분석 봇 시작!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
