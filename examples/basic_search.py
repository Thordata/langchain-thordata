"""Run a ThorData search without creating an agent."""

from langchain_thordata import ThorDataClient

with ThorDataClient() as client:
    result = client.search(
        q="latest AI agent research",
        engine="google_search",
        gl="us",
        hl="en",
        num=5,
    )
    print(result)
