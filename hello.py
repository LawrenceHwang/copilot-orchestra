import asyncio

from copilot import CopilotClient


async def main():
    print("Hello from playground-copilot-sdk!")
    client = CopilotClient()

    await client.start()
    print("Creating session...")
    session = await client.create_session(
        {
            "model": "gemini-3-pro-preview",
            "cli_path": "/opt/homebrew/bin/gemini",
            "cli_args": "--experimental-acp",
            "streaming": False,
        }
    )
    response = await session.send_and_wait({"prompt": "Tell me which model you are?"})

    if response:
        print(response.data.content)
    await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
