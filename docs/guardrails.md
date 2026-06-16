# ChatHR — Product Guardrails

## Overview

ChatHR enforces three layers of input guardrails before any user message reaches storage, retrieval, or the LLM:

1. **Privacy Guard** — blocks high-severity PII (email, phone, Israeli national ID)
2. **Input Guardrails** — blocks inappropriate content, out-of-scope questions, internet search requests
3. **LLM System Instruction** — instructs the model to answer only from official indexed sources

## Guardrail Execution Order

```
User input
  → Privacy Guard (check_text)         [apps/api/app/services/privacy/guard.py]
  → Input Guardrails (check_user_input) [apps/api/app/services/guardrails/input_guard.py]
  → Store user message
  → Retrieval
  → LLM Gateway
```

If blocked at any stage: return 422, do not store, do not call retrieval or LLM.

## Source-Only Policy

- The system answers **only** from official documents indexed in the knowledge base.
- No internet access during answer generation.
- No external knowledge beyond provided indexed sources.
- If sources are insufficient, the system returns: "לא נמצא מקור רשמי מספיק ברור כדי לענות על השאלה."

## No Internet Search Policy

- The system never searches the internet.
- If a user asks to "search Google", "check online", etc., the request is blocked with a 422 response.
- Public message: "המערכת אינה מחפשת באינטרנט בזמן מענה. ניתן לענות רק על בסיס מקורות רשמיים שאונדקסו במערכת."

## Privacy / PII Policy

- High-severity PII (email, Israeli phone numbers, Israeli national ID) blocks the message before storage.
- Medium-severity findings (employee numbers, health/discipline keywords) are flagged but do not block.
- Matched raw text is never returned in API responses or stored in audit logs.

## Inappropriate Content Policy

- Blocked categories: profanity/abuse, sexual content, violent threats, harassment/incitement.
- Applies to both chat messages and feedback comments.
- Conservative approach: avoids blocking legitimate HR terminology.
- Public message: "ההודעה נחסמה: הבקשה מכילה תוכן לא הולם."

## HR-Domain Scope Policy

- The system only answers questions related to HR work in the Israeli civil service.
- Out-of-scope topics: sports, recipes, entertainment, travel booking, personal shopping, coding help, general trivia, medical advice not framed as HR policy, legal advice not framed as civil-service policy.
- Scope check is applied to chat messages only — **not** to feedback comments (feedback can discuss answer quality).
- When uncertain, the system allows the question and relies on retrieval returning no results.
- If any HR keyword is found in the message, the scope check passes.
- Public message: "ניתן לענות רק על שאלות הקשורות לעבודת משאבי אנוש בשירות המדינה."

## No-Source Behavior

- If retrieval returns no chunks: return a safe refusal message without calling the LLM.
- No sources → no LLM call → no answer fabrication.
- This behavior is unchanged by guardrails.

## Prompt Storage Prohibition

- The assembled LLM prompt (system instruction + user question + source chunks) is **never stored** in the database or audit logs.
- Only safe metadata is stored: source chunk IDs, retrieval count, answer mode, index version ID.
- The user's raw query text is stored in the message record but must not appear in audit `metadata_json`.

## Current MVP Limitations

- Guardrail detection is fully deterministic (regex/keyword-based), no ML or external moderation.
- Hebrew keyword lists are conservative; false positives on edge cases are possible.
- Scope blocker uses an HR keyword allowlist — questions with no recognized HR terms and a clear off-topic pattern are blocked; all others pass.
- No rate limiting or abuse detection beyond per-request guardrails.
- No admin UI to review blocked requests (audit log stores the action but not the blocked text).

## Examples of Allowed and Blocked Inputs

| Input | Result | Reason |
|---|---|---|
| "מה הכללים לחישוב ימי מחלה?" | ✅ Allowed | HR keyword present |
| "מה זכאותי לחופשת לידה?" | ✅ Allowed | HR keyword present |
| "מהם תנאי קבלה למשרה בדרגה 40?" | ✅ Allowed | HR keywords present |
| "תחפש לי בגוגל את ההסכם" | ❌ Blocked | internet_search |
| "חפש באינטרנט כמה ימי חופשה מגיעים לי" | ❌ Blocked | internet_search (despite HR keyword — internet search takes priority) |
| "שרמוטה, למה לא קיבלתי ترقية?" | ❌ Blocked | inappropriate_content |
| "מה המתכון לעוגת שוקולד?" | ❌ Blocked | out_of_scope |
| "כמה עולה כרטיס טיסה לפריז?" | ❌ Blocked | out_of_scope |
| "מה זכויות העובד בפרישה?" | ✅ Allowed | HR keyword present |
| "עובד שואל: מה הדין בעניין חישוב ותק?" | ✅ Allowed | HR keyword present |
