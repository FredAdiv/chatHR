# ChatHR — Claude Code Instructions

## Reporting to ChatGPT

When reporting results back to the ChatGPT conversation after completing an instruction, **always send the entire report as a single message**. Do not split the report across multiple `type_text` calls or multiple sends. Compose the full report text first, then send it in one operation.

## Finding the ChatGPT Conversation

When navigating to ChatGPT to check for instructions or to send a report, **always find the most recent conversation in the project "צ'אט נציבות"**. Do not use a hardcoded conversation URL. Instead, navigate to the project and select the latest conversation from the conversation list.

## Scheduled ChatGPT Checks During Task Execution

While executing an instruction (from the moment an instruction is identified until the report has been sent back to ChatGPT), **do not trigger or act on any scheduled ChatGPT conversation checks**. Skip any pending loop iteration that fires during task execution. Resume scheduled checking only after the task is complete and the report has been sent to ChatGPT.

## ChatGPT Handoff Reporting Protocol

When returning execution reports to ChatGPT, do not send one long report if it may be truncated.

Split long reports into small numbered parts using the exact protocol below.

### Required format

Each report part must start with:

```text
REPORT_ID: <short task name or instruction number>
REPORT_PART: <current part>/<total parts or UNKNOWN>
SECTION: <section name>
REPORT_COMPLETE: false