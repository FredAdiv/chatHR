"""Input guardrail service — blocks inappropriate, out-of-scope, or policy-violating user input.

Three guardrail categories (deterministic, no external calls):
  A. inappropriate_content — profanity, sexual content, violent threats, harassment/incitement
  B. out_of_scope         — questions clearly unrelated to HR/civil-service work
  C. internet_search      — user requests web search or Google lookup

Run AFTER Privacy Guard and BEFORE storing user message or calling retrieval/LLM.
Matched raw text is never returned in API responses.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class GuardrailCheckResult:
    allowed: bool
    reason: str | None = None
    category: str | None = None
    public_message: str | None = None


# ── A. Inappropriate content ──────────────────────────────────────────────────
# Conservative — avoids over-blocking legitimate HR terminology

_INAPPROPRIATE_RE = re.compile(
    r'(?:'
    # Hebrew profanity/abuse
    r'זונה|כלבה|מניאק|שרמוטה|תזדיין|תזדייני|תשכב[י]?|בן\s+זונה|בת\s+זונה'
    r'|להזדיין|מזדיין[ת]?|ממזר|פדופיל'
    # Hebrew sexual
    r'|פורנו(?:גרפי[ה]?)?|פורנוגרפ[יה]|סרט[י]?\s+סקס\b|איבר\s+מין\s+(?!בהקשר)'
    # Hebrew violent threats (explicit threat phrases only)
    r'|אני\s+(?:אהרוג|אחסל|אפגע\s+ב|אחרב|אשכור|אשבור)\s+(?:אות[ךוה]|אתכם)'
    r'|(?:תמות|תיהרג|תיחנק)\s+(?:כבר|לך|לכם)'
    # Hebrew harassment/incitement
    r'|מות\s+ל(?:ערבים|יהודים|חרדים|דתיים|חילוניים)\b'
    # English profanity
    r'|fuck(?:ing|er|ed|s)?\b|motherfuck|shit\s+(?:head|face|hole)|\bass\s*hole\b'
    r'|bitch\b(?!\s*(?:session|of))|cunt\b|bastard\b'
    # English sexual
    r'|porn(?:ograph(?:y|ic))?|nude\s+(?:photos?|pics?|images?)|masturbat'
    # English violent threats
    r"|i(?:'ll| will)\s+(?:kill|murder|hurt|attack|rape)\s+(?:you|them|him|her|everyone)"
    r'|kill\s+yourself'
    r')',
    re.IGNORECASE,
)

# ── B. HR domain keywords (allow through scope check if found) ────────────────

_HR_KEYWORDS_RE = re.compile(
    r'(?:'
    r'עובד|עובדת|עובדים|משרה|תקן|דרגה|שכר|חופשה|מחלה|מילואים|מכרז|קליטה|ניוד|פרישה'
    r'|משמעת|תקשי[״"]?ר|נציבות|שירות\s+המדינה|משרד\s+ממשלתי|ממשל[הי]|משאבי\s+אנוש'
    r'|מערכת\s+הבריאות|מערכת\s+הביטחון|גמלה|פנסיה|ותק|קרן\s+השתלמות|חופשת\s+לידה'
    r'|ועדת\s+(?:קבלה|בחינה|משמעת)|מינוי|תנאי\s+(?:קבלה|כשירות|סף|העסקה)'
    r'|human\s+resources?\b|HR\b|civil\s+service|public\s+service'
    r'|salary|position\b|grade\b|sick\s+leave|annual\s+leave|reserve\s+duty'
    r'|discipline\b|recruitment|retirement\b|employee\b|employer\b'
    r')',
    re.IGNORECASE,
)

# ── B. Out-of-scope topic patterns ────────────────────────────────────────────
# Only block clearly off-topic; when uncertain, allow

_OUT_OF_SCOPE_RE = re.compile(
    r'(?:'
    # Sports (specific sport topics, not any mention of sports)
    r'כדורגל\b|כדורסל\b|(?:משחק|תוצאות?)\s+(?:כדורגל|כדורסל|ספורט)\b'
    r'|soccer\s+(?:game|match|player|score|team)'
    r'|(?:who\s+(?:won|scored|plays?\s+for)|game\s+score|match\s+result)\s+(?:in|the)\s+(?:soccer|football|basketball)'
    # Recipes / cooking (clear recipe requests)
    r'|מתכון\s+(?:ל|של|עוגה|עוגיות|עוף|בשר|ירקות|מרק)'
    r'|recipe\s+for\b|how\s+to\s+(?:bake|cook\s+(?!leave|time))\b'
    # Entertainment (specific celebrity/media questions)
    r'|(?:סרט|שיר|אלבום)\s+(?:פופולרי|חדש|הכי\s+טוב)\s+(?:של|ב)'
    r'|celebrity\s+(?:gossip|news|biography(?!\s+(?:that\s+relates|as\s+(?:an?\s+)?(?:civil|public))))'
    # Travel booking
    r'|(?:להזמין|לקנות)\s+(?:כרטיס\s+)?(?:טיסה|כרטיסי\s+טיסה)'
    r'|book\s+(?:a\s+)?(?:flight|hotel\s+room|vacation\s+package)'
    # Online shopping for personal items
    r'|(?:לקנות|לרכוש)\s+(?:נעליים|בגדים|שמלה|מחשב\s+נייד|אייפון|סמסונג)'
    r'|buy\s+(?:shoes|clothes|laptop|iphone|airpods)\s+online'
    r'|aliexpress|ebay\s+(?:order|listing)'
    # Coding/programming help (not work tools)
    r'|(?:כיצד\s+)?לכתוב\s+(?:קוד|תוכנית|פונקציה)\s+ב(?:פייתון|ג\'אווה|javascript)'
    r'|write\s+(?:a\s+)?(?:python|javascript|java|sql)\s+(?:function|script|program)\s+(?:that|to|for)'
    r'|(?:debug|fix)\s+(?:my\s+)?(?:code|script|program)\s+(?:in|written\s+in)'
    # Clear general trivia (not HR-related)
    r'|מה\s+(?:גובהו|משקלו|הגיל\s+של)\s+(?!עובד)'
    r'|who\s+(?:sings?|sang)\s+(?:the\s+song|that\s+song)'
    r'|capital\s+city\s+of\s+(?!israel)'
    r')',
    re.IGNORECASE,
)

# ── C. Internet search requests ───────────────────────────────────────────────

_INTERNET_SEARCH_RE = re.compile(
    r'(?:'
    r'חפש\s+(?:(?:ב|את|ה)?(?:אינטרנט|גוגל|יוטיוב|youtube))'
    r'|תבדוק\s+(?:ב)?(?:אינטרנט|גוגל)'
    r'|תגגל\s+(?:את|לי)'
    r'|search\s+(?:the\s+)?(?:internet|web|google|online)\s+for'
    r'|google\s+(?:it|this|for\s+me|that)'
    r'|look\s+(?:it\s+)?up\s+online'
    r'|find\s+(?:it|this|that)\s+on(?:line|\s+the\s+(?:internet|web))'
    r')',
    re.IGNORECASE,
)

# ── Public messages (Hebrew, shown to user) ───────────────────────────────────

_MSG_INTERNET = (
    "המערכת אינה מחפשת באינטרנט בזמן מענה. "
    "ניתן לענות רק על בסיס מקורות רשמיים שאונדקסו במערכת."
)
_MSG_INAPPROPRIATE = "ההודעה נחסמה: הבקשה מכילה תוכן לא הולם."
_MSG_OUT_OF_SCOPE = (
    "ניתן לענות רק על שאלות הקשורות לעבודת משאבי אנוש בשירות המדינה. "
    "אנא פנה בשאלה מקצועית בתחום זה."
)


# ── Public API ────────────────────────────────────────────────────────────────

def check_user_input(text: str) -> GuardrailCheckResult:
    """Check user input against product guardrails.

    Call order: Privacy Guard → this function → store/retrieve/LLM.
    Matched raw text is NEVER included in the returned result.
    """
    if not text or not text.strip():
        return GuardrailCheckResult(allowed=True)

    # C — internet search (check first: clearest signal, short-circuit)
    if _INTERNET_SEARCH_RE.search(text):
        return GuardrailCheckResult(
            allowed=False,
            reason="internet_search_requested",
            category="internet_search",
            public_message=_MSG_INTERNET,
        )

    # A — inappropriate content
    if _INAPPROPRIATE_RE.search(text):
        return GuardrailCheckResult(
            allowed=False,
            reason="inappropriate_content_detected",
            category="inappropriate_content",
            public_message=_MSG_INAPPROPRIATE,
        )

    # B — out of scope (only block when NO HR keyword is present and off-topic matches)
    if not _HR_KEYWORDS_RE.search(text) and _OUT_OF_SCOPE_RE.search(text):
        return GuardrailCheckResult(
            allowed=False,
            reason="out_of_scope",
            category="out_of_scope",
            public_message=_MSG_OUT_OF_SCOPE,
        )

    return GuardrailCheckResult(allowed=True)


def check_feedback_comment(text: str) -> GuardrailCheckResult:
    """Check feedback comment for inappropriate content only (scope check does not apply).

    Call AFTER Privacy Guard and BEFORE storing the feedback comment.
    """
    if not text or not text.strip():
        return GuardrailCheckResult(allowed=True)
    if _INAPPROPRIATE_RE.search(text):
        return GuardrailCheckResult(
            allowed=False,
            reason="inappropriate_content_detected",
            category="inappropriate_content",
            public_message=_MSG_INAPPROPRIATE,
        )
    return GuardrailCheckResult(allowed=True)
