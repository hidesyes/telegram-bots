from openai import OpenAI
from config import OPENAI_API_KEY, TAVILY_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)

# 유저별 대화 기록 저장 (메모리)
_chat_histories: dict[int, list] = {}

# 유저별 마지막 리라이팅 결과 저장 (후속 수정 지원)
_last_rewrites: dict[int, str] = {}

# 후속 수정 요청 키워드
_FOLLOWUP_KEYWORDS = (
    r"더\s*(구어체|자연스럽게|수정|짧게|길게|쉽게|딱딱하게|풀어서|다듬어|고쳐)"
    r"|글자\s*수\s*(늘려|줄여)"
    r"|다시\s*(해줘|써줘|바꿔줘)"
    r"|좀\s*더\s*(자연스럽게|구어체|짧게|길게)"
)

# AI 감지 우회용 공통 지침 — Burstiness + Perplexity 극대화 전략
_HUMAN_STYLE_RULES = """
[인간 필자 스타일 구현 지침]

## 핵심 목표: Perplexity(어휘 예측 불가성) + Burstiness(문장 길이 변동성) 극대화
AI 탐지 알고리즘은 두 지표로 작동한다:
- Perplexity 낮음 = 다음 단어가 예측 가능 = AI 판정
- Burstiness 낮음 = 문장 길이가 균일 = AI 판정

## 문장 리듬 (Burstiness 극대화)
- 3~5단어 파편 문장과 40단어 이상 복문을 의도적으로 번갈아 쓸 것
- 같은 길이의 문장이 3개 이상 연속되면 안 됨
- 예시: "맞다. 그런데 그 '맞다'는 말이 얼마나 위험한지, 우리는 당연하게 받아들이는 것들 속에서 실제로 얼마나 많은 전제를 아무 검증 없이 믿고 있는지를 생각해보면, 이건 단순한 동의가 아니다."

## 어휘 예측 불가성 (Perplexity 극대화)
- 같은 개념을 같은 문단에서 3가지 이상 다른 방식으로 표현
- 종결어미 다양화: "~이다" 일색 금지. "~더라", "~셈이지", "~지 않을까", "~기도 했다", "~는 건 아닐까"
- 접속어: "그러므로/따라서/결론적으로" 금지 → "그러고 보면", "어찌 됐든", "뭐, 어쨌든", "결국엔" 사용

## 인간적 불완전성 삽입
- 작은 자기 모순이나 망설임: "처음엔 확신했는데... 지금은 좀 다르게 생각한다"
- 주제에서 약간 벗어나는 여담 1~2개 삽입 (전체 맥락은 유지)
- 개인 경험 창작 시 구체적 세부 정보 포함: 장소, 날짜, 대화 상대 이름, 구체적 상황

## 절대 사용 금지 표현
- 나열형: "첫째/둘째/셋째", "①②③", "다음과 같다", "살펴보겠다", "알아보겠다"
- 마무리형: "결론적으로", "이상으로", "위에서 살펴본 바와 같이", "정리하자면"
- AI 과용 표현: "중요한 것은", "주목할 만한", "흥미롭게도", "특히 주목해야 할", "다양한 측면에서"

## 출력 형식 규칙
- 결과물 텍스트만 출력. "네, 리라이팅했습니다" 같은 머리말 절대 금지
- 마크다운 헤더(##), 볼드(**), 리스트(-) 사용 금지 — 일반 텍스트 형식으로만
- 단락 사이는 빈 줄 하나로 구분
"""


def search_web(query: str) -> str:
    """Tavily로 웹 검색. API 키 없으면 빈 문자열 반환."""
    if not TAVILY_API_KEY:
        return ""
    try:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
        results = tavily.search(
            query=query,
            max_results=5,
            search_depth="advanced"
        )
        texts = []
        for r in results.get("results", []):
            texts.append(f"[{r['title']}]\n{r['content'][:600]}")
        return "\n\n".join(texts)
    except Exception:
        return ""


def chat(message: str, user_id: int) -> str:
    """일반 GPT 대화. 유저별 대화 기록 유지."""
    if user_id not in _chat_histories:
        _chat_histories[user_id] = []

    _chat_histories[user_id].append({"role": "user", "content": message})

    # 최근 20턴만 유지
    if len(_chat_histories[user_id]) > 40:
        _chat_histories[user_id] = _chat_histories[user_id][-40:]

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "당신은 친절하고 유능한 AI 어시스턴트입니다. 사용자의 질문에 자연스럽게 답해주세요."},
                *_chat_histories[user_id]
            ]
        )
        reply = response.choices[0].message.content
        _chat_histories[user_id].append({"role": "assistant", "content": reply})
        return reply
    except Exception as e:
        return f"죄송해요, 일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요. (오류: {type(e).__name__})"


def clear_chat_history(user_id: int):
    """유저의 대화 기록 초기화."""
    _chat_histories.pop(user_id, None)
    _last_rewrites.pop(user_id, None)


def save_last_rewrite(user_id: int, result: str):
    """마지막 리라이팅 결과 저장"""
    _last_rewrites[user_id] = result


def get_last_rewrite(user_id: int) -> str | None:
    """마지막 리라이팅 결과 반환"""
    return _last_rewrites.get(user_id)


def self_evaluate(text: str) -> dict:
    """
    리라이팅된 글의 AI 감지 위험도를 자체 평가.
    returns: {"risk": "낮음/중간/높음", "reason": str, "tips": list}
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 GPTZero, Turnitin 같은 AI 감지 도구의 전문가입니다.\n"
                        "제공된 글이 AI가 쓴 글로 탐지될 가능성을 평가하세요.\n\n"
                        "반드시 아래 JSON 형식으로만 반환:\n"
                        '{"risk": "낮음 또는 중간 또는 높음", '
                        '"reason": "판정 이유 1~2줄", '
                        '"tips": ["개선 팁 1", "개선 팁 2"]}'
                    )
                },
                {"role": "user", "content": f"다음 글을 평가해줘:\n\n{text[:2000]}"}
            ],
            max_tokens=300,
            response_format={"type": "json_object"}
        )
        import json
        return json.loads(response.choices[0].message.content)
    except Exception:
        return {"risk": "알 수 없음", "reason": "평가 중 오류 발생", "tips": []}


def rewrite_chunked(text: str, char_count: int = None) -> str:
    """
    5000자 이상 초장문을 2000자 단위로 분할 리라이팅 후 합산.
    각 청크를 독립적으로 리라이팅하되 전체 맥락 일관성 유지.
    """
    CHUNK_SIZE = 2000
    # 문단 단위로 분할 (단어 중간 자르기 방지)
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""

    for para in paragraphs:
        if len(current_chunk) + len(para) > CHUNK_SIZE and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = para
        else:
            current_chunk += ("\n\n" if current_chunk else "") + para

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    results = []
    for i, chunk in enumerate(chunks):
        chunk_instruction = f"[전체 {len(chunks)}개 단락 중 {i+1}번째 단락입니다. 앞뒤 단락과 자연스럽게 이어지도록 작성하세요.]"
        # 마지막 청크에만 글자수 목표 적용
        target = char_count if (char_count and i == len(chunks) - 1) else None
        result = rewrite(chunk_instruction + "\n\n" + chunk, char_count=target)
        results.append(result)

    return "\n\n".join(results)


def rewrite(text: str, char_count: int = None) -> str:
    """
    주어진 텍스트를 AI 감지 우회 스타일로 리라이팅.
    char_count 지정 시 해당 글자수 목표로 작성.
    """
    length_instruction = ""
    if char_count:
        length_instruction = f"\n목표 글자수: {char_count}자 (±10% 허용). 억지로 채우지 말고 내용 깊이로 자연스럽게 맞출 것."

    system_prompt = (
        "당신은 대학 교수 출신 글쓰기 코치입니다. 학생이 쓴 초안을 받아 "
        "내용은 100% 보존하되 표현 방식을 완전히 재구성합니다.\n\n"
        "필수 조건:\n"
        "1. 원문의 모든 주장, 근거, 사실, 수치, 사례는 변경 없이 보존\n"
        "2. 원문에 없는 새로운 주장이나 사실 추가 금지\n"
        "3. 표현, 문장 구조, 어휘, 문단 순서는 자유롭게 재구성\n\n"
        f"{_HUMAN_STYLE_RULES}"
        f"{length_instruction}"
    )

    # max_tokens를 char_count 기반으로 동적 계산 (한국어 1자 ≈ 1.5토큰)
    max_tok = max(4000, int(char_count * 2)) if char_count else 4000

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"다음 글을 리라이팅해줘:\n\n{text}"}
            ],
            max_tokens=min(max_tok, 16000)
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"리라이팅 중 오류가 발생했어요. 잠시 후 다시 시도해주세요. (오류: {type(e).__name__})"


def write_from_topic(topic: str, char_count: int = None) -> str:
    """
    주제를 받아 최신 정보 검색 + 개인 경험 창작으로 글 작성.
    char_count 지정 시 해당 글자수 목표로 작성.
    """
    # Tavily로 최신 정보 검색
    web_context = search_web(topic)
    sources = []
    if web_context:
        web_section = f"\n\n[참고할 최신 정보]\n{web_context}\n\n"
    else:
        web_section = ""

    length_instruction = ""
    if char_count:
        length_instruction = f"\n목표 글자수: {char_count}자 (±10% 허용). 억지로 채우지 말고 내용 깊이로 자연스럽게 맞출 것."

    system_prompt = (
        "당신은 다양한 분야의 칼럼을 써온 프리랜서 작가입니다.\n\n"
        "글쓰기 방침:\n"
        "1. 검색 결과의 사실·통계는 활용하되 문장은 완전히 재구성\n"
        "2. 개인 경험은 구체적으로 창작 (장소, 시간, 대화 상대 포함)\n"
        "3. 학술 보고서가 아닌 읽기 좋은 에세이 형식이 기본값\n\n"
        f"{_HUMAN_STYLE_RULES}"
        f"{length_instruction}"
    )

    user_prompt = (
        f"주제: {topic}"
        f"{web_section}"
        "위 주제로 글을 작성해줘. 개인적인 경험이나 생각도 자연스럽게 섞어서."
    )

    max_tok = max(4000, int(char_count * 2)) if char_count else 4000

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=min(max_tok, 16000)
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"글 작성 중 오류가 발생했어요. 잠시 후 다시 시도해주세요. (오류: {type(e).__name__})"
