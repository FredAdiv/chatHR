# Codex / QA Instructions – ChatHR

## Role

You assist with code review, QA, and quality evaluation for the ChatHR project.

## Scope

- Review code for correctness, security, and adherence to architecture.
- Evaluate RAG output quality against official sources.
- Identify gaps in test coverage.
- Flag potential privacy violations or RBAC gaps.

## Security Checklist

When reviewing code, check for:

- [ ] No secrets in code
- [ ] All secrets loaded from env files
- [ ] Server-side RBAC enforcement (not client-side only)
- [ ] Privacy guard invoked before every model call
- [ ] No full prompts stored by default
- [ ] No personal data sent to external models
- [ ] Audit log records all administrative actions
- [ ] No anonymous access paths

## RAG Quality Criteria

A good RAG response must:
- Cite at least one official source
- Include a link to the source (and section/clause if possible)
- Not invent information when no source exists
- Expose source conflicts rather than hiding them
- Apply authority hierarchy correctly

## Test Coverage Expectations

- Unit tests: core business logic, privacy guard, authority ranking
- Integration tests: API endpoints, database operations
- Evals: RAG retrieval quality, citation accuracy, context handling

## Architecture Compliance

Verify:
- No direct OpenRouter calls outside LLM Gateway
- Index updates build new version aside, never modify active index directly
- FAQ items that are not approved/active are excluded from RAG
- FAQ never overrides התקשי״ר or salary agreements
