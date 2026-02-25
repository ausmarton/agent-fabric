# agent-fabric: MCP Server Integrations

This document shows how to wire real MCP (Model Context Protocol) tool servers into agent-fabric specialist packs. The Phase 5 infrastructure (`MCPAugmentedPack`, `MCPSessionManager`) handles the session lifecycle transparently — you only need to add config entries.

---

## Quick start

MCP servers are attached per-specialist using `mcp_servers:` in your `FabricConfig`. Tools from each server are merged into the pack's tool definitions and prefixed as `mcp__<name>__<tool>` to avoid collisions.

```yaml
# ~/.fabric/config.yaml  (or path in FABRIC_CONFIG_PATH)

models:
  fast:
    base_url: http://localhost:11434/v1
    model: qwen2.5:7b
  quality:
    base_url: http://localhost:11434/v1
    model: qwen2.5:14b

specialists:
  enterprise_research:
    description: "Enterprise search across GitHub, Confluence, and Jira."
    workflow: enterprise_research
    capabilities: [enterprise_search, github_search, systematic_review]
    mcp_servers:
      - name: github
        transport: stdio
        command: npx
        args: ["--yes", "--", "@modelcontextprotocol/server-github"]
        env:
          GITHUB_TOKEN: "${GITHUB_TOKEN}"   # expand from environment
      - name: confluence
        transport: sse
        url: https://your-confluence.example.com/rest/mcp
        headers:
          Authorization: "Bearer ${CONFLUENCE_TOKEN}"
```

---

## GitHub

**Package:** `@modelcontextprotocol/server-github`
**Transport:** stdio
**Auth:** GitHub Personal Access Token (PAT) or GitHub App token

### Prerequisites

```bash
# Install the package globally (one-time)
npm install -g @modelcontextprotocol/server-github

# Or let npx download it on first use (slower start)
```

### Config

```yaml
mcp_servers:
  - name: github
    transport: stdio
    command: npx
    args: ["--yes", "--", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: "ghp_your_token_here"
    timeout_s: 30.0
```

### Available tools (representative — check server version for full list)

| Tool name (prefixed) | Description |
|---------------------|-------------|
| `mcp__github__search_repositories` | Search GitHub repositories |
| `mcp__github__get_file_contents` | Read a file from a repo |
| `mcp__github__list_issues` | List issues for a repository |
| `mcp__github__search_code` | Search code across GitHub |
| `mcp__github__create_issue` | Create an issue (write access required) |
| `mcp__github__create_pull_request` | Create a PR (write access required) |

### Verification test

```bash
GITHUB_TOKEN=ghp_... pytest tests/test_mcp_real_github.py -k real_mcp -v
```

---

## Confluence

**Package:** `@modelcontextprotocol/server-confluence` (Atlassian) or a community package
**Transport:** SSE (REST/MCP bridge) or stdio
**Auth:** Confluence API token

> **Status:** Confluence MCP servers are emerging. Check Atlassian's marketplace or community packages for the latest official support. The config below uses a generic pattern.

### Config (SSE transport)

```yaml
mcp_servers:
  - name: confluence
    transport: sse
    url: https://your-org.atlassian.net/rest/mcp/v1
    headers:
      Authorization: "Bearer ${CONFLUENCE_API_TOKEN}"
      X-Atlassian-Token: "no-check"
    timeout_s: 30.0
```

### Config (stdio — community server)

```yaml
mcp_servers:
  - name: confluence
    transport: stdio
    command: npx
    args: ["--yes", "--", "@your-org/confluence-mcp-server"]
    env:
      CONFLUENCE_BASE_URL: "https://your-org.atlassian.net"
      CONFLUENCE_EMAIL: "you@example.com"
      CONFLUENCE_API_TOKEN: "your_token_here"
    timeout_s: 30.0
```

---

## Jira

**Package:** `@modelcontextprotocol/server-jira` (community) or Atlassian's official package
**Transport:** stdio or SSE
**Auth:** Jira API token

> **Status:** Official Atlassian MCP support is in beta. Check https://community.atlassian.com for the current recommended package.

### Config

```yaml
mcp_servers:
  - name: jira
    transport: stdio
    command: npx
    args: ["--yes", "--", "@your-org/jira-mcp-server"]
    env:
      JIRA_BASE_URL: "https://your-org.atlassian.net"
      JIRA_EMAIL: "you@example.com"
      JIRA_API_TOKEN: "your_token_here"
    timeout_s: 30.0
```

---

## Filesystem (built-in / testing)

**Package:** `@modelcontextprotocol/server-filesystem`
**Transport:** stdio
**Auth:** None (local filesystem)

Useful for testing the MCP pipeline end-to-end without cloud dependencies.

```yaml
mcp_servers:
  - name: fs
    transport: stdio
    command: npx
    args: ["--yes", "--", "@modelcontextprotocol/server-filesystem", "/path/to/workspace"]
    timeout_s: 15.0
```

---

## Containerised specialist + MCP

You can combine `container_image` with `mcp_servers`. The registry applies wrappers in order: `inner → MCPAugmentedPack (if mcp_servers) → ContainerisedSpecialistPack (if container_image)`. The MCP server runs on the **host** (not inside the container), while shell commands run inside the container.

```yaml
specialists:
  secure_engineering:
    description: "Engineering with isolated shell + GitHub MCP access."
    workflow: engineering
    capabilities: [code_execution, github_search]
    container_image: "python:3.12-slim"
    mcp_servers:
      - name: github
        transport: stdio
        command: npx
        args: ["--yes", "--", "@modelcontextprotocol/server-github"]
        env:
          GITHUB_TOKEN: "ghp_your_token_here"
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `RuntimeError: mcp package not installed` | The `mcp` Python package is absent | `pip install agent-fabric[mcp]` |
| `RuntimeError: Failed to start Podman container` | Podman not installed or image not pulled | Install Podman; `podman pull <image>` |
| MCP tool returns `{"error": "..."}` | Tool call failed on the server | Check the MCP server logs; verify auth tokens and API permissions |
| All tools timeout | Server subprocess didn't start | Check `npx` is in PATH; check `GITHUB_TOKEN` is valid |
| `npx` hangs | Node.js module download on first use | Pre-install: `npm install -g @modelcontextprotocol/server-github` |
