"""Tool-loop prompt templates (JSON schema for tool/final actions)."""

TOOL_LOOP_ENGINEERING = """You can call tools by emitting JSON exactly in this schema:
{{
  "action": "tool",
  "tool_name": "<one of: {tool_names}>",
  "args": {{ ... }}
}}
Or, when you are done:
{{
  "action": "final",
  "summary": "What you did",
  "artifacts": ["relative/path1", "relative/path2"],
  "next_steps": ["..."],
  "notes": "Any caveats, test commands, etc"
}}

Do NOT wrap JSON in markdown fences. Output only JSON."""

TOOL_LOOP_RESEARCH = """You can call tools by emitting JSON exactly in this schema:
{{
  "action": "tool",
  "tool_name": "<one of: {tool_names}>",
  "args": {{ ... }}
}}
Or, when you are done:
{{
  "action": "final",
  "deliverables": {{
     "executive_summary": "...",
     "key_findings": ["..."],
     "evidence_table_path": "research/evidence_table.md",
     "screening_log_path": "research/screening_log.md",
     "bibliography_path": "research/bibliography.md",
     "gaps_and_future_work": ["..."]
  }},
  "citations": [{{"url":"...","fetched_at":"...","claim":"..."}}],
  "notes": "How to reproduce searches"
}}

Rules:
- Only cite URLs you fetched via fetch_url.
- Maintain screening log and evidence table as files in workspace.
- Output only JSON (no markdown fences)."""
