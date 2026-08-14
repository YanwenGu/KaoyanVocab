import sqlite3
import time
import json
import os
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime, timedelta
from urllib.parse import urlparse
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vocab_data.db")

session = requests.Session()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["null"],  # file:// pages send Origin: null
    allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def block_foreign_origins(request: Request, call_next):
    """Hard-block requests from non-local web pages.

    CORS alone only stops the *browser* from reading responses; a malicious
    page could still trigger server-side side effects (e.g. POST /api/words,
    which spends DeepSeek API credits). This middleware rejects such requests
    with 403 before they reach any handler. Requests without an Origin header
    (curl, the browser extension via host_permissions) pass through.
    """
    origin = request.headers.get("origin")
    if origin:
        allowed = origin == "null"
        if not allowed:
            try:
                parsed = urlparse(origin)
                allowed = (
                    parsed.scheme in ("http", "https")
                    and parsed.hostname in ("127.0.0.1", "localhost")
                )
            except ValueError:
                allowed = False
        if not allowed:
            return JSONResponse(status_code=403, content={"detail": "Forbidden origin"})
    return await call_next(request)

SYSTEM_PROMPT = """你是一个精通考研英语（NETEM）的词汇专家。请对用户输入的英文单词或短语进行多维度深度分析。

【核心任务】
1. 词形还原（Lemmatization）：严格遵循下方【词形还原判定决策树】处理输入表达式。
2. 考研词义深度解析：提取符合考研大纲及真题常考的中文释义，特别是熟词生义。
3. 真实/高仿真长难句：提供真实真题例句或100%还原考研学术阅读风格的高质量长难句。

【词形还原（Lemmatization）判定决策树】
请严格按以下步骤分析输入文本，并在 "lemma" 字段中输出最终还原结果：

第一步：判断输入是【单个单词】、【多字词组/短语/固定搭配】还是【句型/完整句子/带有占位符（如 A, B, sb., sth.）的表达】？
  - 如果是【单个单词】：转到第二步。
  - 如果是【多字词组/短语/固定搭配】：转到第三步。
  - 如果是【句型/完整句子/带有占位符的表达】：转到第四步。

第二步：【单个单词】还原规则
  - 仅还原纯语法变形，不改变核心词义。
  - 规则：名词复数->单数 (apples->apple)；动词时态/分词->原形 (ran->run, making->make)；形容词/副词比较级/最高级->原级 (better->good)。

第三步：【多字词组/短语/固定搭配】还原规则（重点！）
  - 核心原则：只还原短语外部的整体时态或复数，严禁破坏短语内部固有的词形。
  - 允许还原的情况（外部变形）：
    * 短语整体处于过去时态/进行时态，仅还原其核心动词：
      例：kept on doing -> keep on doing（只还原 kept，保持 doing 结构不变）
      例：took for granted -> take for granted（只还原 took，严禁将 granted 还原为 grant）
    * 短语整体处于复数形式，仅还原末尾名词：
      例：boiling points -> boiling point（只还原 points，保持 boiling 不变）
  - 严禁还原的情况（内部固有形态保护）：
    * 内部的分词修饰、形容词化分词、被动语态或固定搭配成分，必须保持原样，不得剥离 -ed 或 -ing。
      例：applied linguistics（应用语言学，不得还原为 apply linguistic）
      例：with flying colors（出色地，不得还原为 with fly color）
      例：armed forces（武装力量，不得还原为 arm force）
      例：united nations（联合国，不得还原为 unite nation）
      例：advanced technology（先进技术，不得还原为 advance technology）
      例：be supposed to（应该，不得还原为 be suppose to）
      例：given that（考虑到，不得还原为 give that）

第四步：【句型/完整句子/带有占位符的表达】还原规则
  - 核心原则：严禁将其缩减、简化或剥离为单个单词。
  - 规则：必须保持其完整结构（包含占位符、主谓宾等全部成分），直接将原始输入作为 "lemma" 输出。
    例：We need A alongside B -> We need A alongside B（严禁缩减为 alongside）
    例：keep sb. informed -> keep sb. informed
    例：do sb. a favor -> do sb. a favor

【详细输出规则与要求】

1. 考研中文释义 (meaning)：
   - 优先输出考研大纲及历年真题中最常考的释义。
   - 特别注意：如果是"熟词生义"（如 school 意为"鱼群"，court 意为"招致/奉承"），请务必在释义中体现，并用括号标注，例如："招致，追求（熟词生义）"。

2. 例句与翻译 (example_en / example_cn)：
   - 优先使用真实考研英语真题中的原句。
   - 若真题未收录，必须自主设计一句符合考研长难句风格（包含从句、非谓语、插入语等，长度在15-25词左右，语境偏向严肃学术期刊文风）的例句。
   - 给出准确、通顺的中文翻译。

3. 派生词 (derivatives)：
   - 仅对"单词"生成派生词，最多提供3个最常见、最符合考研大纲的派生词。
   - 如果输入是"词组/短语"，则 derivatives 必须返回空数组 []。

【输出格式控制】
请务必直接输出合法的 JSON 格式。不要包含任何 Markdown 标记（如 ```json），不要有任何首尾解释性文字。

JSON Schema 结构必须严格如下：
{
  "lemma": "按照判定决策树处理后的结果",
  "pos": "词性缩写（如 n. / v. / adj. / adv. 等，短语或词组此项留空 \"\"）",
  "meaning": "考研精准释义（突出考研核心及熟词生义）",
  "example_en": "考研真题例句或考研长难句风格的高质量例句",
  "example_cn": "对应的精准中文翻译",
  "derivatives": [
    {
      "word": "派生词",
      "pos": "词性缩写",
      "meaning": "考研核心中文释义"
    }
  ]
}"""


@contextmanager
def get_db():
    """Context manager for SQLite connections.

    Guarantees the connection is always closed, even when a handler raises
    mid-request (previously several code paths leaked connections). Writes are
    committed explicitly by the caller, as before.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def parse_derivatives(raw):
    """Parse the derivatives JSON text column into a list, tolerating bad data."""
    try:
        return json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        return []


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vocabulary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expression TEXT NOT NULL,
                pos TEXT,
                meaning TEXT,
                example_en TEXT,
                example_cn TEXT,
                derivatives TEXT,
                created_at INTEGER NOT NULL
            )
        """)
        try:
            conn.execute("ALTER TABLE vocabulary ADD COLUMN is_important INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # column already exists

        # SM-2 spaced repetition fields
        for col, definition in [
            ("repetition", "INTEGER NOT NULL DEFAULT 0"),
            ("ease_factor", "REAL NOT NULL DEFAULT 2.5"),
            ("interval", "INTEGER NOT NULL DEFAULT 0"),
            ("next_review", "TEXT"),
            ("last_review", "TEXT"),
            ("assigned_date", "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE vocabulary ADD COLUMN {col} {definition}")
            except sqlite3.OperationalError:
                pass  # column already exists

        # Review history table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS review_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word_id INTEGER NOT NULL,
                reviewed_at INTEGER NOT NULL,
                quality INTEGER NOT NULL,
                FOREIGN KEY (word_id) REFERENCES vocabulary(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_review_log_word_id ON review_log(word_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vocabulary_next_review ON vocabulary(next_review)")

        conn.commit()


def call_deepseek(system_prompt: str, user_message: str) -> dict:
    """Call DeepSeek with retry + exponential backoff for transient failures.

    Retries up to 3 times total: rate-limit (429) and 5xx errors back off
    1s / 2s; malformed responses are retried once more with a 1s pause.
    """
    for attempt in range(3):
        try:
            resp = session.post(
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-v4-flash",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
                timeout=20,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        except requests.RequestException as e:
            # Only retry transient HTTP errors (429 / 5xx); treat connect
            # failures and other request errors as terminal.
            resp_obj = getattr(e, "response", None)
            status_code = resp_obj.status_code if resp_obj is not None else None
            if attempt < 2 and status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            raise
        except (json.JSONDecodeError, KeyError):
            if attempt < 2:
                time.sleep(1)
                continue
            raise


SUGGEST_PROMPT = """你是一个英语拼写检查专家。用户输入了一个可能是英文单词或短语的文本。
请检查该文本是否是合法的英文单词或短语：
- 如果拼写完全正确，返回 {"correct": true, "suggestions": []}
- 如果可能存在拼写错误，返回 {"correct": false, "suggestions": ["推测1", "推测2", ...]}，suggestions 数组包含最多5个最可能的正确拼写推测
请务必直接输出合法的 JSON 格式，不要包含任何 markdown 标记，也不要包含任何解释性文本。"""

UNIFIED_PROMPT = """你是一个精通考研英语（NETEM）的词汇专家，同时具备强大的拼写检查能力。请对用户输入的英文单词或短语进行多维度深度分析。

【核心任务】
1. 拼写检查：评估输入是否是合法、常用的英文单词或短语。
2. 词形还原（Lemmatization）：严格遵循下方【词形还原判定决策树】处理输入表达式。
3. 考研词义深度解析：提取符合考研大纲及真题常考的中文释义，特别是熟词生义。
4. 真实/高仿真长难句：提供真实真题例句或100%还原考研学术阅读风格（如科技、经济、社会、人文科学等主题）的高质量长难句。

【词形还原（Lemmatization）判定决策树】
请严格按以下步骤分析输入文本，并在 "lemma" 字段中输出最终还原结果：

第一步：判断输入是【单个单词】、【多字词组/短语/固定搭配】还是【句型/完整句子/带有占位符（如 A, B, sb., sth.）的表达】？
  - 如果是【单个单词】：转到第二步。
  - 如果是【多字词组/短语/固定搭配】：转到第三步。
  - 如果是【句型/完整句子/带有占位符的表达】：转到第四步。

第二步：【单个单词】还原规则
  - 仅还原纯语法变形，不改变核心词义。
  - 规则：名词复数->单数 (apples->apple)；动词时态/分词->原形 (ran->run, making->make)；形容词/副词比较级/最高级->原级 (better->good)。

第三步：【多字词组/短语/固定搭配】还原规则（重点！）
  - 核心原则：只还原短语外部的整体时态或复数，严禁破坏短语内部固有的词形。
  - 允许还原的情况（外部变形）：
    * 短语整体处于过去时态/进行时态，仅还原其核心动词：
      例：kept on doing -> keep on doing（只还原 kept，保持 doing 结构不变）
      例：took for granted -> take for granted（只还原 took，严禁将 granted 还原为 grant）
    * 短语整体处于复数形式，仅还原末尾名词：
      例：boiling points -> boiling point（只还原 points，保持 boiling 不变）
  - 严禁还原的情况（内部固有形态保护）：
    * 内部的分词修饰、形容词化分词、被动语态或固定搭配成分，必须保持原样，不得剥离 -ed 或 -ing。
      例：applied linguistics（应用语言学，不得还原为 apply linguistic）
      例：with flying colors（出色地，不得还原为 with fly color）
      例：armed forces（武装力量，不得还原为 arm force）
      例：united nations（联合国，不得还原为 unite nation）
      例：advanced technology（先进技术，不得还原为 advance technology）
      例：be supposed to（应该，不得还原为 be suppose to）
      例：given that（考虑到，不得还原为 give that）

第四步：【句型/完整句子/带有占位符的表达】还原规则
  - 核心原则：严禁将其缩减、简化或剥离为单个单词。
  - 规则：必须保持其完整结构（包含占位符、主谓宾等全部成分），直接将原始输入作为 "lemma" 输出。
    例：We need A alongside B -> We need A alongside B（严禁缩减为 alongside）
    例：keep sb. informed -> keep sb. informed
    例：do sb. a favor -> do sb. a favor

【详细输出规则与要求】

1. 拼写检查规则：
   - 如果拼写完全正确或为常见固定表达，spell_check.correct 为 true，spell_check.suggestions 为空数组。
   - 如果检测到拼写错误，spell_check.correct 为 false，并在 suggestions 中返回最多5个最可能的正确候选词。

2. 考研中文释义 (meaning)：
   - 优先输出考研大纲及历年真题中最常考的释义。
   - 特别注意：如果是"熟词生义"（如 school 意为"鱼群"，court 意为"招致/奉承"），请务必在释义中体现，并用括号标注，例如："招致，追求（熟词生义）"。

3. 例句与翻译 (example_en / example_cn)：
   - 优先使用真实考研英语真题（英语一或英语二）中的原句。
   - 若真题未收录，必须自主设计一句符合考研长难句风格（包含从句、非谓语、插入语等，长度在15-25词左右，语境偏向严肃学术期刊文风）的例句。
   - 给出信、达、雅的中文翻译。

4. 派生词 (derivatives)：
   - 仅对"单词"生成派生词，最多提供3个最常见、最符合考研大纲的派生词。
   - 如果输入是"词组/短语"，则 derivatives 必须返回空数组 []。

【输出格式控制】
请务必直接输出合法的 JSON 格式。不要包含任何 Markdown 标记（如 ```json），不要有任何首尾解释性文字。

JSON Schema 定义必须严格符合以下两类情况：

若拼写正确（correct 为 true）：
{
  "spell_check": {
    "correct": true,
    "suggestions": []
  },
  "lemma": "按照判定决策树处理后的结果",
  "pos": "词性缩写（如 n. / v. / adj. / adv. 等，短语或词组此项留空 \"\"）",
  "meaning": "考研精准释义（突出考研核心及熟词生义）",
  "example_en": "考研真题例句或考研长难句风格的高质量例句",
  "example_cn": "对应的精准中文翻译",
  "derivatives": [
    {
      "word": "派生词",
      "pos": "词性缩写",
      "meaning": "考研核心中文释义"
    }
  ]
}

若拼写可能错误（correct 为 false）：
{
  "spell_check": {
    "correct": false,
    "suggestions": ["候选词1", "候选词2", "候选词3", "候选词4", "候选词5"]
  },
  "lemma": "",
  "pos": "",
  "meaning": "",
  "example_en": "",
  "example_cn": "",
  "derivatives": []
}"""


class WordRequest(BaseModel):
    expression: str
    skip_spell_check: bool = False
    cached_analysis: dict | None = None
    raw_input: bool = False


def _find_duplicate(conn, expression: str):
    """Case-insensitive duplicate lookup. Returns the existing row or None."""
    return conn.execute(
        "SELECT id, expression, meaning, is_important FROM vocabulary WHERE LOWER(expression) = LOWER(?) LIMIT 1",
        (expression,),
    ).fetchone()


def _duplicate_response(row) -> dict:
    return {
        "duplicate": True,
        "id": row["id"],
        "expression": row["expression"],
        "meaning": row["meaning"],
        "is_important": row["is_important"],
    }


@app.get("/api/words")
def list_words(important: bool = False):
    with get_db() as conn:
        if important:
            rows = conn.execute(
                "SELECT * FROM vocabulary WHERE is_important = 1 ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM vocabulary ORDER BY created_at DESC"
            ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["derivatives"] = parse_derivatives(d.get("derivatives"))
        results.append(d)
    return results


@app.get("/api/words/latest-id")
def get_latest_id():
    with get_db() as conn:
        row = conn.execute("SELECT MAX(id) FROM vocabulary").fetchone()
    return {"latest_id": row[0] or 0}


# ============== Daily Review Recommendation Algorithm ==============

def adaptive_daily_target(conn):
    """Adaptive daily word target in [100, 300], based on last 7 days of review performance."""
    start_ts = int(datetime.combine(date.today() - timedelta(days=7), datetime.min.time()).timestamp())
    rows = conn.execute(
        "SELECT quality, reviewed_at FROM review_log WHERE reviewed_at >= ?",
        (start_ts,),
    ).fetchall()
    if not rows:
        return 100
    total = len(rows)
    accuracy = sum(1 for r in rows if r["quality"] >= 3) / total
    active_days = len({datetime.fromtimestamp(r["reviewed_at"]).date() for r in rows})
    volume_norm = min(1.0, (total / max(1, active_days)) / 300)
    blend = 0.7 * accuracy + 0.3 * volume_norm
    return max(100, min(300, round(100 + 200 * blend)))


def priority_score(row, today, failures):
    """Higher = review sooner. Weighs important flag, overdue days, low ease, repeated failures."""
    score = 0
    if row["is_important"]:
        score += 50
    next_review = row["next_review"]
    if next_review:
        try:
            overdue_days = (today - date.fromisoformat(next_review)).days
        except ValueError:
            overdue_days = 0
        score += max(0, overdue_days) * 2
    score += max(0.0, 2.5 - (row["ease_factor"] or 2.5)) * 20
    score += failures * 15
    if not row["repetition"]:
        score += 10
    return score


def _interleave(review_list, new_list):
    """Deterministically spread new words evenly among review words."""
    if not new_list:
        return review_list
    if not review_list:
        return new_list
    step = len(review_list) / len(new_list)
    result = []
    oi = ni = 0
    while oi < len(review_list) or ni < len(new_list):
        if ni >= len(new_list):
            result.extend(review_list[oi:])
            break
        n_ov = max(0, min(round((ni + 1) * step) - oi, len(review_list) - oi))
        result.extend(review_list[oi:oi + n_ov])
        oi += n_ov
        result.append(new_list[ni])
        ni += 1
        if oi >= len(review_list):
            result.extend(new_list[ni:])
            break
    return result


def _build_daily_list(conn, today, commit=True):
    """Build today's review list. Important words are always included first;
    remaining slots filled by overdue words (priority order) then new words,
    interleaved, up to the adaptive daily target. Returns word dicts."""
    today_iso = today.isoformat()
    target = adaptive_daily_target(conn)

    fail_counts = {}
    for r in conn.execute(
        "SELECT word_id, COUNT(*) AS c FROM review_log WHERE quality < 3 GROUP BY word_id"
    ):
        fail_counts[r["word_id"]] = r["c"]

    overdue_rows = conn.execute(
        "SELECT * FROM vocabulary WHERE next_review IS NOT NULL AND next_review <= ?",
        (today_iso,),
    ).fetchall()
    new_rows = conn.execute(
        "SELECT * FROM vocabulary WHERE next_review IS NULL"
    ).fetchall()

    forced_review = [r for r in overdue_rows if r["is_important"]]
    normal_review = [r for r in overdue_rows if not r["is_important"]]
    forced_new = [r for r in new_rows if r["is_important"]]
    normal_new = [r for r in new_rows if not r["is_important"]]

    score_key = lambda r: priority_score(r, today, fail_counts.get(r["id"], 0))
    forced_review.sort(key=score_key, reverse=True)
    normal_review.sort(key=score_key, reverse=True)
    forced_new.sort(key=lambda r: r["created_at"], reverse=True)
    normal_new.sort(key=lambda r: r["created_at"], reverse=True)

    # Guarantee a small floor of new words even when the backlog is heavy.
    new_floor = min(10, len(forced_new) + len(normal_new))
    review_cap = max(len(forced_review), target - len(forced_new) - new_floor)
    review_list = forced_review + normal_review[: max(0, review_cap - len(forced_review))]
    new_budget = max(new_floor, target - len(review_list) - len(forced_new))
    new_list = forced_new + normal_new[: max(0, new_budget)]

    words = _interleave(review_list, new_list)
    ids = [w["id"] for w in words]

    if commit and ids:
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE vocabulary SET assigned_date = ? WHERE id IN ({placeholders})",
            [today_iso] + ids,
        )
        conn.commit()

    results = []
    for r in words:
        d = dict(r)
        d["derivatives"] = parse_derivatives(d.get("derivatives"))
        results.append(d)
    return results


@app.get("/api/words/due")
def get_due_words():
    """Get today's review list. On first open of the day, builds and assigns it;
    later calls return the day's list minus already-reviewed words."""
    today = date.today()
    today_iso = today.isoformat()

    with get_db() as conn:
        assigned_rows = conn.execute(
            "SELECT * FROM vocabulary WHERE assigned_date = ?",
            (today_iso,),
        ).fetchall()

        if assigned_rows:
            today_ts_start = int(datetime.combine(today, datetime.min.time()).timestamp())
            reviewed_ids = {r[0] for r in conn.execute(
                "SELECT DISTINCT word_id FROM review_log WHERE reviewed_at >= ?",
                (today_ts_start,),
            ).fetchall()}
            results = [dict(r) for r in assigned_rows if r["id"] not in reviewed_ids]
            for r in results:
                r["derivatives"] = parse_derivatives(r.get("derivatives"))
            return results

        return _build_daily_list(conn, today, commit=True)


@app.get("/api/words/assigned-today")
def get_assigned_today_count():
    """Get count of words assigned today that haven't been reviewed yet."""
    today = date.today()
    today_iso = today.isoformat()

    with get_db() as conn:
        assigned_count = conn.execute(
            "SELECT COUNT(*) FROM vocabulary WHERE assigned_date = ?",
            (today_iso,),
        ).fetchone()[0]

        # Nothing assigned yet: preview the list the due endpoint would build.
        if assigned_count == 0:
            words = _build_daily_list(conn, today, commit=False)
            return {"count": len(words)}

        today_ts_start = int(datetime.combine(today, datetime.min.time()).timestamp())
        reviewed_ids = {r[0] for r in conn.execute(
            "SELECT DISTINCT word_id FROM review_log WHERE reviewed_at >= ?",
            (today_ts_start,),
        ).fetchall()}
        assigned_rows = conn.execute(
            "SELECT id FROM vocabulary WHERE assigned_date = ?",
            (today_iso,),
        ).fetchall()
        remaining = sum(1 for r in assigned_rows if r[0] not in reviewed_ids)
    return {"count": remaining}


@app.post("/api/words")
def add_word(req: WordRequest):
    expression = req.expression.strip()
    if not expression:
        raise HTTPException(status_code=400, detail="expression 不能为空")

    # Fast path: exact duplicate (case-insensitive) — no API call spent.
    with get_db() as conn:
        existing = _find_duplicate(conn, expression)
    if existing:
        return _duplicate_response(existing)

    if req.skip_spell_check and req.cached_analysis:
        data = req.cached_analysis
    else:
        prompt = SYSTEM_PROMPT if req.skip_spell_check else UNIFIED_PROMPT
        try:
            data = call_deepseek(prompt, expression)
        except requests.RequestException as e:
            raise HTTPException(status_code=502, detail=f"API 请求失败: {str(e)}")
        except (json.JSONDecodeError, KeyError) as e:
            raise HTTPException(status_code=500, detail=f"响应解析失败: {str(e)}")

    if not req.skip_spell_check:
        spell_check = data.get("spell_check", {})
        if spell_check.get("correct") is False:
            return {
                "spell_check": {
                    "correct": False,
                    "suggestions": spell_check.get("suggestions", []),
                },
                "cached_analysis": {
                    "lemma": data.get("lemma", expression),
                    "pos": data.get("pos", ""),
                    "meaning": data.get("meaning", ""),
                    "example_en": data.get("example_en", ""),
                    "example_cn": data.get("example_cn", ""),
                    "derivatives": data.get("derivatives", []),
                },
            }

    lemma = expression if req.raw_input else data.get("lemma", expression)
    pos = data.get("pos", "")
    meaning = data.get("meaning", "")
    example_en = data.get("example_en", "")
    example_cn = data.get("example_cn", "")
    derivatives = json.dumps(data.get("derivatives", []), ensure_ascii=False)
    created_at = int(time.time())

    with get_db() as conn:
        # Second dedup pass on the lemma form (e.g. "running" -> "run" already exists).
        existing = _find_duplicate(conn, lemma)
        if existing:
            return _duplicate_response(existing)
        try:
            cur = conn.execute(
                "INSERT INTO vocabulary (expression, pos, meaning, example_en, example_cn, derivatives, created_at, is_important) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                (lemma, pos, meaning, example_en, example_cn, derivatives, created_at),
            )
            conn.commit()
            new_id = cur.lastrowid
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"数据库写入失败: {str(e)}")

    return {
        "id": new_id,
        "expression": lemma,
        "pos": pos,
        "meaning": meaning,
        "example_en": example_en,
        "example_cn": example_cn,
        "derivatives": parse_derivatives(derivatives),
        "created_at": created_at,
        "is_important": 0,
    }


@app.get("/api/words/{word_id}")
def get_word(word_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM vocabulary WHERE id = ?", (word_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    d = dict(row)
    d["derivatives"] = parse_derivatives(d.get("derivatives"))
    return d


@app.delete("/api/words/{word_id}")
def delete_word(word_id: int):
    with get_db() as conn:
        cur = conn.execute("DELETE FROM vocabulary WHERE id = ?", (word_id,))
        conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"ok": True}


class ImportantRequest(BaseModel):
    is_important: bool


class UpdateWordRequest(BaseModel):
    expression: str | None = None
    pos: str | None = None
    meaning: str | None = None
    example_en: str | None = None
    example_cn: str | None = None
    derivatives: list[dict] | None = None


@app.patch("/api/words/{word_id}")
def update_word(word_id: int, req: UpdateWordRequest):
    """Update one or more fields of a word entry."""
    updates = {}
    for field in ("expression", "pos", "meaning", "example_en", "example_cn"):
        val = getattr(req, field, None)
        if val is not None:
            updates[field] = val
    if req.derivatives is not None:
        updates["derivatives"] = json.dumps(req.derivatives, ensure_ascii=False)

    if not updates:
        raise HTTPException(status_code=400, detail="至少需要提供一个要更新的字段")

    with get_db() as conn:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [word_id]
        cur = conn.execute(
            f"UPDATE vocabulary SET {set_clause} WHERE id = ?",
            values,
        )
        conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"ok": True}


@app.patch("/api/words/{word_id}/important")
def toggle_important(word_id: int, req: ImportantRequest):
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE vocabulary SET is_important = ? WHERE id = ?",
            (1 if req.is_important else 0, word_id),
        )
        conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"ok": True}


@app.get("/api/suggest")
def suggest(q: str):
    q = q.strip()
    if not q:
        return {"correct": True, "suggestions": []}
    try:
        data = call_deepseek(SUGGEST_PROMPT, q)
        return {"correct": data.get("correct", True), "suggestions": data.get("suggestions", [])}
    except Exception:
        return {"correct": True, "suggestions": []}


# ============== SM-2 Spaced Repetition System ==============

def calculate_next_review(repetition: int, ease_factor: float, interval: int, quality: int):
    """
    Simplified SM-2 algorithm.
    quality: 1 = forgot, 5 = easy
    Returns: (new_repetition, new_ease_factor, new_interval, next_review_date)
    """
    if quality < 3:
        # Failed: reset to beginning
        new_repetition = 0
        new_interval = 1
    else:
        # Success
        if repetition == 0:
            new_interval = 1
        elif repetition == 1:
            new_interval = 6
        else:
            new_interval = round(interval * ease_factor)
        new_repetition = repetition + 1

    # Update ease factor
    new_ease_factor = ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    new_ease_factor = max(1.3, new_ease_factor)

    # Calculate next review date
    next_review = (date.today() + timedelta(days=new_interval)).isoformat()

    return new_repetition, round(new_ease_factor, 2), new_interval, next_review


class ReviewRequest(BaseModel):
    quality: int  # 1 = forgot, 5 = easy


@app.post("/api/words/{word_id}/review")
def record_review(word_id: int, req: ReviewRequest):
    """Record a review result and update SM-2 scheduling."""
    if req.quality not in (1, 5):
        raise HTTPException(status_code=400, detail="quality must be 1 or 5")

    with get_db() as conn:
        row = conn.execute("SELECT * FROM vocabulary WHERE id = ?", (word_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="记录不存在")

        row = dict(row)
        repetition = row.get("repetition", 0) or 0
        ease_factor = row.get("ease_factor", 2.5) or 2.5
        interval = row.get("interval", 0) or 0
        now_ts = int(time.time())
        today = date.today().isoformat()

        # Calculate new scheduling
        new_repetition, new_ease_factor, new_interval, next_review = calculate_next_review(
            repetition, ease_factor, interval, req.quality
        )

        # Update vocabulary scheduling fields
        conn.execute("""
            UPDATE vocabulary
            SET repetition = ?, ease_factor = ?, interval = ?,
                next_review = ?, last_review = ?
            WHERE id = ?
        """, (new_repetition, new_ease_factor, new_interval,
              next_review, today, word_id))

        # Insert review log
        conn.execute("""
            INSERT INTO review_log (word_id, reviewed_at, quality)
            VALUES (?, ?, ?)
        """, (word_id, now_ts, req.quality))

        conn.commit()

    return {
        "ok": True,
        "next_review": next_review,
        "interval": new_interval,
        "ease_factor": new_ease_factor,
        "repetition": new_repetition,
    }


@app.get("/api/review-stats")
def review_stats():
    """Get review statistics for the dashboard."""
    today = date.today().isoformat()
    today_ts_start = int(datetime.combine(date.today(), datetime.min.time()).timestamp())

    with get_db() as conn:
        # Words reviewed today
        today_count = conn.execute("""
            SELECT COUNT(DISTINCT word_id) FROM review_log
            WHERE reviewed_at >= ?
        """, (today_ts_start,)).fetchone()[0]

        # Total words with review history
        reviewed_count = conn.execute("""
            SELECT COUNT(DISTINCT word_id) FROM review_log
        """).fetchone()[0]

        # Words due today (overdue + due today, excluding never-reviewed)
        due_count = conn.execute("""
            SELECT COUNT(*) FROM vocabulary
            WHERE next_review IS NOT NULL AND next_review <= ?
        """, (today,)).fetchone()[0]

        # New (never-reviewed) words
        new_count = conn.execute("""
            SELECT COUNT(*) FROM vocabulary WHERE next_review IS NULL
        """).fetchone()[0]

        # Today's accuracy
        today_reviews = conn.execute("""
            SELECT quality FROM review_log WHERE reviewed_at >= ?
        """, (today_ts_start,)).fetchall()
        if today_reviews:
            total = len(today_reviews)
            successes = sum(1 for r in today_reviews if r[0] >= 3)
            accuracy = round(successes / total * 100, 1)
        else:
            accuracy = 0

        # Streak: consecutive days with at least 1 review
        streak = 0
        check_date = date.today()
        while True:
            day_start = int(datetime.combine(check_date, datetime.min.time()).timestamp())
            day_end = int(datetime.combine(check_date + timedelta(days=1), datetime.min.time()).timestamp())
            count = conn.execute("""
                SELECT COUNT(*) FROM review_log
                WHERE reviewed_at >= ? AND reviewed_at < ?
            """, (day_start, day_end)).fetchone()[0]
            if count > 0:
                streak += 1
                check_date -= timedelta(days=1)
            else:
                break

        # Total reviews all time
        total_reviews = conn.execute("SELECT COUNT(*) FROM review_log").fetchone()[0]

    return {
        "today_reviewed": today_count,
        "today_due": due_count,
        "new_words": new_count,
        "today_accuracy": accuracy,
        "streak": streak,
        "total_reviewed": reviewed_count,
        "total_reviews": total_reviews,
    }


class ImportRequest(BaseModel):
    words: list[dict]


IMPORT_COLUMNS = (
    "expression", "pos", "meaning", "example_en", "example_cn", "derivatives",
    "is_important", "repetition", "ease_factor", "interval",
    "next_review", "last_review", "assigned_date", "created_at",
)


@app.get("/api/export")
def export_words():
    """Export the full vocabulary as JSON (backup / migration)."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM vocabulary ORDER BY created_at DESC").fetchall()
    words = []
    for r in rows:
        d = dict(r)
        d["derivatives"] = parse_derivatives(d.get("derivatives"))
        words.append(d)
    return {"words": words, "exported_at": int(time.time())}


@app.post("/api/import")
def import_words(req: ImportRequest):
    """Import words from an export file. Case-insensitive duplicates are skipped."""
    imported = skipped = 0
    now = int(time.time())
    with get_db() as conn:
        existing_exprs = {
            r[0].lower() for r in conn.execute("SELECT expression FROM vocabulary").fetchall()
        }
        for w in req.words:
            expr = str(w.get("expression", "")).strip()
            if not expr:
                skipped += 1
                continue
            key = expr.lower()
            if key in existing_exprs:
                skipped += 1
                continue

            row = {}
            for col in IMPORT_COLUMNS:
                val = w.get(col)
                if val is None:
                    continue
                if col == "derivatives":
                    val = json.dumps(val, ensure_ascii=False) if isinstance(val, (list, dict)) else str(val)
                elif col == "is_important":
                    val = 1 if val else 0
                row[col] = val
            row.setdefault("created_at", now)

            cols = ", ".join(row.keys())
            placeholders = ", ".join("?" * len(row))
            conn.execute(
                f"INSERT INTO vocabulary ({cols}) VALUES ({placeholders})",
                list(row.values()),
            )
            existing_exprs.add(key)
            imported += 1
        conn.commit()
    return {"imported": imported, "skipped": skipped}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
