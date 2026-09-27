# Python 版 LangChain Thordata

将 [Thordata](https://www.thordata.com/serp-api/mcp?utm_source=MCP&utm_term=mcp)
SERP 接入 Python 应用和 LangChain agent，用于实时搜索。

此包通过 Python 客户端和 LangChain 搜索工具提供 Thordata 搜索能力。版本 1
面向 Thordata 的同步 SERP 端点，仅公开搜索结果 API，不公开 Web Scraper API
或 `google_webpage` 引擎。

## 安装

```bash
pip install langchain-thordata
```

用于本地开发：

```bash
python -m pip install -e ".[test]"
```

## 配置

设置 Thordata SERP API 密钥：

```bash
export THORDATA_API_KEY="your-api-key"
```

`THORDATA_API_TOKEN` 可作为兼容别名使用。默认 API URL 是
`https://scraperapi.thordata.com/request`；开发时可用 `THORDATA_SERP_API_URL`
覆盖它。

## Python 客户端

```python
from langchain_thordata import ThorDataClient

with ThorDataClient() as client:
    results = client.search(
        q="latest AI agent research",
        engine="google_search",
        gl="us",
        hl="en",
        num=10,
    )
    print(results)
```

客户端会复用 HTTP 连接池，直到调用 `close()` 或 `aclose()`；建议使用同步或异步
上下文管理器。客户端还为异步调用者提供 `await client.asearch(...)`。当前
`/request` 端点不保证返回 HTML，因此客户端只公开 JSON 搜索方法。

客户端接受 `/request` 支持的所有表单参数。API 原生参数既可以作为关键字参数传入，
也可以放在第一个映射参数中：

```python
flights = client.search(
    {
        "departure_id": "SFO",
        "arrival_id": "JFK",
        "outbound_date": "2026-10-01",
        "return_date": "2026-10-08",
    },
    engine="google_flights",
)
```

两种传参形式中的便捷名称 `query`、`country` 和 `language` 都会映射到 `q`、
`gl` 和 `hl`。显式 API 原生名称（如 `q`、`gl`、`hl` 和 `text`）保持不变。
对于 Yandex，`query` 或 `q` 会作为 `text` 发送。

## LangChain 工具

```python
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
```

工具可通过 `params` 使用专用参数：

```python
result = tool.invoke(
    {
        "engine": "google_scholar_author",
        "params": {"author_id": "EicYvbwAAAAJ", "sort": "pubdate"},
    }
)
```

该工具可以直接传给 LangChain agent：

```python
from langchain.agents import create_agent
from langchain_thordata import ThorDataSearchTool

agent = create_agent(model, tools=[ThorDataSearchTool()])
```

agent 示例需要单独的 `langchain` 包；该集成的运行时依赖仍限制为
`langchain-core`。

## 支持的引擎

- Google 搜索：`google`, `google_light`, `google_web`, `google_images`,
  `google_videos`, `google_news`, `google_shopping`, `google_local`,
  `google_product`, `google_lens`, `google_trends`, `google_maps`,
  `google_hotels`, `google_jobs` 和 `google_ai_mode`。
- Google 垂直搜索：`google_scholar`, `google_scholar_cite`,
  `google_scholar_author`, `google_play`, `google_play_product`,
  `google_play_games`, `google_play_movies`, `google_play_books`,
  `google_finance`, `google_finance_markets`, `google_flights`,
  `google_patents` 和 `google_patents_details`。
- Bing：`bing`, `bing_images`, `bing_videos`, `bing_news`, `bing_shopping` 和
  `bing_maps`。
- 其他提供方：`yandex` 和 `duckduckgo`。对于 Yandex，LangChain 的
  `query` 字段会发送为 API 要求的 `text` 参数。

为保持兼容性，发送请求前 `google_search` 会映射到 `google`，`google_places`
会映射到 `google_local`。

不受支持的参数会从请求中省略。不受支持的引擎会被拒绝，因为静默切换搜索来源会改变用户意图。

每个请求都会发送固定的集成元数据：

- 平台：`langchain`
- 来源：`python-sdk`

这些值会同时作为请求头和表单元数据发送。当前 Thordata 服务会记录表单元数据，
但不会将其转发给搜索提供方。

API 密钥永远不会包含在工具输出或异常消息中。业务码 `300` 会抛出
`ThorDataNotCollectedError`；所有 API 异常仍保留数值 `code` 供程序判断。

客户端会在 LangChain 工具序列化之前统一解析 JSON 字符串形式的响应 envelope，
因此调用方只需要解析工具输出一次。

## 开发

```bash
ruff check .
pytest
python -m build
```

实时集成测试应使用专用测试账号和 API 密钥。单元测试使用内存中的 HTTP 传输，
不会调用 Thordata 服务。

## 了解更多

- [Thordata SERP API](https://www.thordata.com/serp-api/mcp?utm_source=MCP&utm_term=mcp)
