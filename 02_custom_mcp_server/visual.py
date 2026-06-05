
import os
import sys
import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

load_dotenv()

_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
mcp = FastMCP("visual_code_server", transport_security=_security)


async def get_code(url: str) -> str:
    """
    Fetch source code from a GitHub URL.

    Args:
        url: GitHub URL of the code file
    Returns:
        str: Source code content or error message
    """
    USER_AGENT = "visual-fastmcp/0.1"

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/plain"
    }

    async with httpx.AsyncClient() as client:
        try:
            raw_url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
            response = await client.get(raw_url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.text
        except Exception as e:
            return f"Error fetching code: {str(e)}"


@mcp.tool()
async def visualize_code(url: str) -> str:
    """
    Fetch source code from a GitHub file URL and return its contents.

    Args:
        url: The GitHub file URL (blob URL or raw URL)

    Returns:
        The raw source code of the file.
    """
    code = await get_code(url)
    return code


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    if "--http" in sys.argv:
        transport = "http"
    elif "--sse" in sys.argv:
        transport = "sse"

    port = int(os.getenv("PORT", "8080"))

    if transport == "http":
        import uvicorn
        print(f"Starting MCP server with Streamable HTTP on port {port}", flush=True)
        uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=port, proxy_headers=True, forwarded_allow_ips="*")
    elif transport == "sse":
        import uvicorn
        print(f"Starting MCP server with SSE on port {port}", flush=True)
        uvicorn.run(mcp.sse_app(), host="0.0.0.0", port=port, proxy_headers=True, forwarded_allow_ips="*")
    else:
        mcp.run()
