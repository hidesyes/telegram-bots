import io
import re
import logging
# deploy test
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from config import TELEGRAM_TOKEN, ALLOWED_USER_ID
from ai import rewrite, write_from_topic, chat, clear_chat_history
from parser import parse_file

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# "주제 :" 또는 "주제:" 패턴
TOPIC_PATTERN = re.compile(r"^주제\s*[:：]\s*(.+)", re.DOTALL)
REWRITE_KEYWORDS = re.compile(
    r"리라이팅|다시\s*써|고쳐\s*써|재작성|paraphrase|수정해\s*줘|바꿔\s*줘|다듬어\s*줘|첨삭|"
    r"표현\s*바꿔|사람이\s*쓴\s*것처럼|AI\s*안\s*잡히게|감지\s*우회|투린틴|turnitin|gpt\s*zero"
)
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
        "1️⃣ 자유 대화\n"
        "평소엔 GPT처럼 자유롭게 대화하세요!\n\n"
        "2️⃣ 리라이팅 모드\n"
        "긴 글을 붙여넣으면 자동으로 리라이팅해드려요.\n"
        "'이 글 리라이팅해줘 2000자' 처럼 글자수 지정도 가능해요.\n"
        "파일(txt/docx/pdf/hwpx)을 전송해도 됩니다!\n\n"
        "3️⃣ 주제 작성 모드\n"
        "주제 : 경제에서 작용하는 심리학 2가지 1500자\n"
        "('주제 :' 로 시작하면 최신 정보 검색 후 작성해드려요)\n\n"
        "📌 명령어:\n"
        "/clear — 대화 기록 초기화"
    )


# ─────────────────────────────────────────────
# 텍스트 메시지 처리
# ─────────────────────────────────────────────
async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update.effective_user.id):
        return
    clear_chat_history(update.effective_user.id)
    await update.message.reply_text("대화 기록을 초기화했어요!")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update.effective_user.id):
        return

    text = update.message.text.strip()
    user_id = update.effective_user.id
    topic_match = TOPIC_PATTERN.match(text)

    if topic_match:
        # 주제 작성 모드
        topic_full = topic_match.group(1).strip()
        char_count = extract_char_count(topic_full)
        # 글자수 패턴을 주제에서 제거하고 AI에 전달
        clean_topic = re.sub(r"\d+\s*자", "", topic_full).strip()
        await update.message.reply_text("🔍 최신 정보 검색 중... 잠시만 기다려주세요!")
        result = write_from_topic(clean_topic, char_count=char_count)
        await send_result(update, result, filename="essay.txt")

    elif len(text) > 300 or REWRITE_KEYWORDS.search(text):
        # 리라이팅 모드: 300자 이상의 긴 글이거나 리라이팅 키워드 포함
        char_count = extract_char_count(text)
        clean_text = re.sub(r"\d+\s*자", "", text).strip()
        clean_text = re.sub(
            r"(리라이팅|다시\s*써|고쳐\s*써|재작성|수정해\s*줘|바꿔\s*줘|다듬어\s*줘|첨삭|표현\s*바꿔|사람이\s*쓴\s*것처럼|AI\s*안\s*잡히게)\s*(줘|주세요|해줘|해주세요)?",
            "", clean_text
        ).strip()

        if len(clean_text) < 30:
            await update.message.reply_text("리라이팅할 글을 붙여넣어 주세요!\n또는 파일(txt/docx/pdf/hwpx)을 전송해주세요.")
            return

        await update.message.reply_text("✍️ 리라이팅 중... 잠시만 기다려주세요!")
        result = rewrite(clean_text, char_count=char_count)
        await send_result(update, result, filename="rewritten.txt")

    else:
        # 일반 GPT 대화 모드
        reply = chat(text, user_id)
        await update.message.reply_text(reply)


# ─────────────────────────────────────────────
# 파일 처리 (txt / docx / pdf)
# ─────────────────────────────────────────────
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update.effective_user.id):
        return

    doc = update.message.document
    filename = doc.file_name or ""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if ext not in ("txt", "docx", "pdf", "hwpx", "hwp"):
        await update.message.reply_text(
            "❌ 지원하지 않는 파일 형식이에요.\n"
            "txt, docx, pdf, hwpx 파일만 업로드해주세요!"
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
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("AI 리라이팅 봇 시작!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
