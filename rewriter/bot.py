import io
import re
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from config import TELEGRAM_TOKEN, ALLOWED_USER_ID
from ai import rewrite, write_from_topic
from parser import parse_file

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# "주제 :" 또는 "주제:" 패턴
TOPIC_PATTERN = re.compile(r"^주제\s*[:：]\s*(.+)", re.DOTALL)
# 글자수 추출: "1500자", "2000 자" 등
CHAR_COUNT_PATTERN = re.compile(r"(\d+)\s*자")


def check_auth(user_id: int) -> bool:
    return user_id == ALLOWED_USER_ID


def extract_char_count(text: str) -> int | None:
    """텍스트에서 글자수 추출. 없으면 None."""
    match = CHAR_COUNT_PATTERN.search(text)
    if match:
        return int(match.group(1))
    return None


async def send_result(update: Update, result: str, filename: str = "result.txt"):
    """결과 길이에 따라 텍스트 또는 파일로 전송."""
    if len(result) <= 4096:
        await update.message.reply_text(result)
    else:
        file_obj = io.BytesIO(result.encode("utf-8"))
        file_obj.name = filename
        await update.message.reply_document(
            document=file_obj,
            filename=filename,
            caption=f"결과가 길어서 파일로 보내드릴게요! ({len(result)}자)"
        )


# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update.effective_user.id):
        return

    await update.message.reply_text(
        "안녕하세요! AI 리라이팅 봇입니다 ✍️\n\n"
        "📝 사용법:\n\n"
        "1️⃣ 리라이팅 모드\n"
        "글을 그냥 붙여넣으면 자동으로 리라이팅해드려요.\n"
        "글자수를 지정하고 싶으면: '이 글 리라이팅해줘 2000자' 처럼 써주세요.\n"
        "파일(txt/docx/pdf)을 전송해도 됩니다!\n\n"
        "2️⃣ 주제 작성 모드\n"
        "주제 : 경제에서 작용하는 심리학 2가지 1500자\n"
        "(위처럼 '주제 :' 또는 '주제:' 로 시작하면 최신 정보 검색 후 작성해드려요)"
    )


# ─────────────────────────────────────────────
# 텍스트 메시지 처리
# ─────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update.effective_user.id):
        return

    text = update.message.text.strip()
    topic_match = TOPIC_PATTERN.match(text)

    if topic_match:
        # 주제 작성 모드
        topic_full = topic_match.group(1).strip()
        char_count = extract_char_count(topic_full)

        await update.message.reply_text(
            "🔍 최신 정보 검색 중... 잠시만 기다려주세요!"
        )

        result = write_from_topic(topic_full, char_count=char_count)
        await send_result(update, result, filename="essay.txt")

    else:
        # 리라이팅 모드
        char_count = extract_char_count(text)

        # 글자수 지시어 제거한 순수 본문 추출
        # (예: "이 글 리라이팅해줘 2000자" → 앞부분이 본문인 경우를 처리)
        # 짧은 명령어만 있는 경우 안내
        clean_text = re.sub(r"\d+\s*자", "", text).strip()
        clean_text = re.sub(r"(리라이팅|다시\s*써|고쳐)\s*(줘|주세요|해줘|해주세요)", "", clean_text).strip()

        if len(clean_text) < 30:
            await update.message.reply_text(
                "리라이팅할 글을 붙여넣어 주세요!\n"
                "또는 파일(txt/docx/pdf)을 전송해주세요."
            )
            return

        await update.message.reply_text("✍️ 리라이팅 중... 잠시만 기다려주세요!")

        result = rewrite(clean_text, char_count=char_count)
        await send_result(update, result, filename="rewritten.txt")


# ─────────────────────────────────────────────
# 파일 처리 (txt / docx / pdf)
# ─────────────────────────────────────────────
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update.effective_user.id):
        return

    doc = update.message.document
    filename = doc.file_name or ""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if ext not in ("txt", "docx", "pdf"):
        await update.message.reply_text(
            "❌ 지원하지 않는 파일 형식이에요.\n"
            "txt, docx, pdf 파일만 업로드해주세요!"
        )
        return

    await update.message.reply_text(f"📂 파일 읽는 중... ({filename})")

    file = await doc.get_file()
    file_bytes = await file.download_as_bytearray()

    parsed_text = parse_file(bytes(file_bytes), filename)

    if not parsed_text.strip():
        await update.message.reply_text("❌ 파일에서 텍스트를 추출하지 못했어요. 다른 파일을 시도해주세요.")
        return

    # 캡션에서 글자수 추출 (선택사항)
    caption = update.message.caption or ""
    char_count = extract_char_count(caption)

    await update.message.reply_text(
        f"✅ 텍스트 추출 완료! ({len(parsed_text)}자)\n"
        "✍️ 리라이팅 중... 잠시만 기다려주세요!"
    )

    result = rewrite(parsed_text, char_count=char_count)
    await send_result(update, result, filename="rewritten.txt")


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("AI 리라이팅 봇 시작!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
