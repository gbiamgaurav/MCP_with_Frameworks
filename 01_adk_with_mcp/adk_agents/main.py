"""
Programmatic runner — bypasses the `adk` CLI.

Usage:
    cd 01_adk_with_mcp
    python adk_agents/main.py single   "What's the weather in Tokyo and AAPL stock price?"
    python adk_agents/main.py multi    "Research weather in London and NYC, then write a report."

Requires GOOGLE_API_KEY in .env or environment.
"""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

load_dotenv(Path(__file__).parent.parent / ".env")

APP_NAME = "mcp_learning"
USER_ID  = "dev_user"
SESSION_ID = "session_001"


async def run(agent, query: str) -> str:
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=SESSION_ID,
    )

    runner = Runner(
        agent=agent,
        app_name=APP_NAME,
        session_service=session_service,
    )

    message = types.Content(
        role="user",
        parts=[types.Part(text=query)],
    )

    print(f"\nUser: {query}\n")
    print("=" * 60)

    final_text = ""
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=SESSION_ID,
        new_message=message,
    ):
        if event.is_final_response():
            if event.content and event.content.parts:
                final_text = event.content.parts[0].text
                print(f"Agent ({event.author}):\n{final_text}")
        elif hasattr(event, "content") and event.content:
            # intermediate agent steps in the pipeline
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    print(f"[{event.author}]: {part.text[:200]}...")

    return final_text


def main():
    mode  = sys.argv[1] if len(sys.argv) > 1 else "single"
    query = sys.argv[2] if len(sys.argv) > 2 else ""

    if mode == "single":
        from single_agent.agent import root_agent
        if not query:
            query = "What's the weather in London and Tokyo? Also calculate sqrt(144) + 2**10."
    elif mode == "multi":
        from multi_agent.agent import root_agent
        if not query:
            query = "Research weather in London, New York, and Tokyo. Compare temperatures and write a report."
    else:
        print("Usage: python main.py [single|multi] [optional query]")
        sys.exit(1)

    asyncio.run(run(root_agent, query))


if __name__ == "__main__":
    main()
