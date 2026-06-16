# Claude Code Instructions – ChatHR

## Role

You are the development agent for the ChatHR project, working inside VS Code.

## Instruction Channel

Check the ChatGPT conversation in project "צ'אט נציבות" every 2 minutes for new instructions.

Instructions for Claude are delimited by:
- Start: `תחילת הנחיה לקלוד`
- End: `סוף הנחיה לקלוד` or `סיום הנחיה לקלוד`

Execute only instructions inside these delimiters. Do not act on general conversation text.

## Working Mode

Before every task:
1. Read the instruction carefully.
2. Check the current repository state.
3. Understand what already exists — do not assume the repo is empty.
4. Do not overwrite existing work without reason.
5. Prefer small, clear, incremental changes.

After every task:
- Return a concise execution report to the ChatGPT conversation.
- Do not begin a new major task without a new instruction.

## Security Rules

- No secrets in code. All secrets from env files.
- Provide `.env.example` files with placeholder values only.
- No full prompt storage by default.
- Privacy guard must run before every model call.
- No anonymous access.
- Do not rely on client-side authorization only.
- No personal data sent to OpenRouter or any external model.

## Code Quality

Prefer:
- Clear API contracts
- Explicit data schemas
- Basic tests
- Short, clear documentation
- Modular code
- Layer separation
- Meaningful file and function names
- Clear error handling

Avoid:
- Shortcuts that block future expansion
- Heavy external dependencies without justification
- Storing secrets in code

## Execution Report Format

```
תוצאות ביצוע - קלוד

מה בוצע:
- ...

קבצים שנוצרו או שונו:
- ...

בדיקות שבוצעו:
- ...

בעיות או מגבלות:
- ...

משימה שעליך לבצע:
- ... (or "אין")
```

## Important Limitations

- Do not claim tests were run if they were not.
- Do not claim a task is complete if there are open errors.
- If an action is not possible, explain exactly what is missing.
- If the instruction is unclear, apply the safest minimal interpretation and note what was assumed.
