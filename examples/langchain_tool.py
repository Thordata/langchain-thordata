"""Invoke the ThorData LangChain tool directly."""

from langchain_thordata import ThorDataSearchTool

tool = ThorDataSearchTool()
result = tool.invoke(
    {
        "query": "latest AI agent research",
        "engine": "google_news",
        "country": "us",
        "language": "en",
        "num": 5,
    }
)
print(result)
