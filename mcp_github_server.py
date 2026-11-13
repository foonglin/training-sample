import json
import os
import re
import requests
import base64

# Compatibility import for MCP 2.x vs 1.x
try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer

mcp = MCPServer("GitHubArchitectMCPServer")

def parse_github_url(url: str) -> tuple[str, str] | None:
    url = url.strip().rstrip("/").rstrip(".git")
    match = re.search(r"github\.com/([^/]+)/([^/]+)", url)
    return (match.group(1), match.group(2)) if match else None

@mcp.tool()
def fetch_repo_metadata(url: str) -> str:
    parsed = parse_github_url(url)
    if not parsed: return json.dumps({"status": "error", "message": "Invalid GitHub URL."})
    owner, repo = parsed
    try:
        meta = requests.get(f"https://api.github.com/repos/{owner}/{repo}").json()
        if meta.get("message") == "Not Found":
            return json.dumps({"status": "error", "message": "Repo not found or private."})
        readme_resp = requests.get(f"https://api.github.com/repos/{owner}/{repo}/readme")
        readme = ""
        if readme_resp.status_code == 200:
            readme = base64.b64decode(readme_resp.json().get("content", "")).decode("utf-8")[:3000]
        return json.dumps({
            "status": "success", "name": meta.get("full_name"),
            "description": meta.get("description", ""), "language": meta.get("language", ""),
            "stars": meta.get("stargazers_count", 0), "topics": meta.get("topics", []),
            "readme_preview": readme
        })
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

@mcp.tool()
def search_architecture_insights(url: str) -> str:
    parsed = parse_github_url(url)
    if not parsed: return json.dumps({"status": "error", "message": "Invalid URL."})
    owner, repo = parsed
    query = f"site:github.com/{owner}/{repo} OR '{owner}/{repo}' architecture tech stack pros cons"
    try:
        from google.adk.tools import google_search
        results = google_search(query, max_results=5)
        return json.dumps({"status": "success", "search_results": results})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

if __name__ == "__main__":
    mcp.run(transport="stdio")
