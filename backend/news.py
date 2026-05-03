from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


POSITIVE_WORDS = ["상향", "호조", "성장", "수주", "실적", "흑자", "확대", "돌파", "강세", "승인", "beat", "beats", "strong", "upbeat", "excellent", "record", "growth", "profit", "profits", "soaring", "surge", "raises", "raised", "buyback", "contract", "contracts", "guidance", "outperform", "upgrade", "higher", "thumping"]
NEGATIVE_WORDS = ["하향", "부진", "적자", "감소", "소송", "규제", "리콜", "약세", "차질", "경고", "miss", "misses", "weak", "weakness", "cuts", "cut", "downgrade", "falls", "drops", "loss", "losses", "warning", "probe", "lawsuit", "delay", "concerns", "slump", "lower", "cancels", "cancel"]
EVENT_KEYWORDS = {
    "실적": ["실적", "매출", "영업이익", "순이익", "earnings", "revenue"],
    "목표가": ["목표가", "투자의견", "상향", "하향", "target", "rating"],
    "수주": ["수주", "계약", "공급", "order", "contract"],
    "규제": ["규제", "소송", "조사", "sanction", "lawsuit"],
    "신제품": ["출시", "신제품", "AI", "반도체", "product", "launch"],
}


def summarize_news(title: str, summary: str | None = None) -> dict:
    body = clean_summary_body(title, summary)
    text = f"{title or ''} {body}".strip()
    compact = re.sub(r"\s+", " ", body or title or "")
    if len(compact) > 190:
        compact = compact[:187].rstrip() + "..."
    tags = [tag for tag, words in EVENT_KEYWORDS.items() if any(word.lower() in text.lower() for word in words)]
    score = sum(1 for word in POSITIVE_WORDS if word.lower() in text.lower()) - sum(
        1 for word in NEGATIVE_WORDS if word.lower() in text.lower()
    )
    sentiment = "positive" if score > 0 else "negative" if score < 0 else "neutral"
    return {
        "ai_summary": compact or "요약할 뉴스 본문이 없습니다.",
        "sentiment": sentiment,
        "tags": tags or ["일반"],
    }


def clean_summary_body(title: str, summary: str | None = None) -> str:
    body = re.sub(r"\s+", " ", summary or "").strip()
    headline = re.sub(r"\s+", " ", title or "").strip()
    if not body:
        return ""
    if headline and body.lower().startswith(headline.lower()):
        body = body[len(headline):].strip(" -:|·")
    sentences = re.split(r"(?<=[.!?。！？])\s+", body)
    seen = set()
    cleaned = []
    for sentence in sentences:
        compact = re.sub(r"[\W_]+", "", sentence).lower()
        if not compact or compact in seen:
            continue
        seen.add(compact)
        cleaned.append(sentence.strip())
    body = " ".join(cleaned).strip()
    if headline and re.sub(r"[\W_]+", "", body).lower() == re.sub(r"[\W_]+", "", headline).lower():
        return ""
    return body
def canonical_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    split = urlsplit(raw)
    query = [
        (key, value)
        for key, value in parse_qsl(split.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid", "ocid"}
    ]
    return urlunsplit((split.scheme, split.netloc.lower(), split.path.rstrip("/"), urlencode(query), ""))


def title_fingerprint(title: str) -> str:
    text = re.sub(r"[\W_]+", "", (title or "").lower())
    return text[:80]


def news_id(url: str, title: str) -> str:
    raw = canonical_url(url) or title
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")



