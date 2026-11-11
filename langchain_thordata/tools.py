"""LangChain tools backed by ThorData SERP search."""

from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .client import ThorDataClient
from .web_scraper import SUPPORTED_WEB_SCRAPERS

SearchEngine = Literal[
    "google",
    "google_search",
    "google_light",
    "google_web",
    "google_images",
    "google_videos",
    "google_news",
    "google_shopping",
    "google_local",
    "google_places",
    "google_product",
    "google_lens",
    "google_trends",
    "google_maps",
    "google_hotels",
    "google_jobs",
    "google_scholar",
    "google_scholar_cite",
    "google_scholar_author",
    "google_play",
    "google_play_product",
    "google_play_games",
    "google_play_movies",
    "google_play_books",
    "google_finance",
    "google_finance_markets",
    "google_flights",
    "google_patents",
    "google_patents_details",
    "google_ai_mode",
    "bing",
    "bing_images",
    "bing_videos",
    "bing_news",
    "bing_shopping",
    "bing_maps",
    "yandex",
    "duckduckgo",
]

WebScraperId = Literal[
    "linkedin_company_information_by-url",
    "linkedin_job_listings_information_by-job-url",
    "youtube_video-post_by-keyword",
    "facebook_profile_by-profiles-url",
    "youtube_video-post_by-explore",
    "twitter_profile_by-profileurl",
    "amazon_product_by-category-url",
]


class ThorDataSearchInput(BaseModel):
    """Input schema for a ThorData web search."""

    query: str | None = Field(
        default=None,
        min_length=1,
        description="The search query; sent as text for Yandex and q for other engines.",
    )
    engine: SearchEngine = Field(
        default="google_search",
        description="The ThorData SERP engine to use.",
    )
    country: str | None = Field(
        default=None,
        min_length=2,
        max_length=2,
        description="Two-letter country code used to localize results, for example 'us'.",
    )
    language: str | None = Field(
        default=None,
        min_length=2,
        description="Language code for result presentation, for example 'en'.",
    )
    location: str | None = Field(
        default=None,
        min_length=1,
        description="A geographic location used to localize the search.",
    )
    num: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Maximum number of results requested from the API.",
    )
    page: int | None = Field(
        default=None,
        ge=1,
        description="One-based result page number.",
    )
    safe: Literal["active", "off"] | None = Field(
        default=None,
        description="Safe-search behavior.",
    )
    time_range: str | None = Field(
        default=None,
        min_length=1,
        description="Google tbs time filter, such as 'qdr:d' for the past day.",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Additional ThorData /request form parameters for specialized engines, "
            "such as departure_id, arrival_id, product_id, or author_id."
        ),
    )


class ThorDataSearchTool(BaseTool):
    """LangChain tool that searches the web through ThorData SERP."""

    name: str = "thordata_search"
    description: str = (
        "Search current Google, Bing, Yandex, or DuckDuckGo results with ThorData. "
        "This includes web, news, image, video, shopping, local, maps, travel, "
        "scholar, patent, finance, app-store, and Google AI result types."
    )
    args_schema: type[BaseModel] = ThorDataSearchInput
    client: ThorDataClient = Field(exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(
        self,
        *,
        client: ThorDataClient | None = None,
        api_key: str | None = None,
        api_url: str | None = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> None:
        resolved_client = client or ThorDataClient(
            api_key=api_key,
            api_url=api_url,
            timeout=timeout,
        )
        super().__init__(client=resolved_client, **kwargs)

    def _run(
        self,
        query: str | None = None,
        engine: SearchEngine = "google_search",
        country: str | None = None,
        language: str | None = None,
        location: str | None = None,
        num: int | None = None,
        page: int | None = None,
        safe: Literal["active", "off"] | None = None,
        time_range: str | None = None,
        params: dict[str, Any] | None = None,
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        del run_manager
        result = self.client.search(
            params,
            query=query,
            engine=engine,
            country=country,
            language=language,
            location=location,
            num=num,
            page=page,
            safe=safe,
            tbs=time_range,
        )
        return self._serialize(result)

    async def _arun(
        self,
        query: str | None = None,
        engine: SearchEngine = "google_search",
        country: str | None = None,
        language: str | None = None,
        location: str | None = None,
        num: int | None = None,
        page: int | None = None,
        safe: Literal["active", "off"] | None = None,
        time_range: str | None = None,
        params: dict[str, Any] | None = None,
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        del run_manager
        result = await self.client.asearch(
            params,
            query=query,
            engine=engine,
            country=country,
            language=language,
            location=location,
            num=num,
            page=page,
            safe=safe,
            tbs=time_range,
        )
        return self._serialize(result)

    @staticmethod
    def _serialize(result: Any) -> str:
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)


class ThorDataWebScraperInput(BaseModel):
    """Input schema for a supported ThorData Web Scraper."""

    spider_id: WebScraperId = Field(
        description=(
            "One of the seven supported ThorData Web Scraper IDs: "
            + ", ".join(SUPPORTED_WEB_SCRAPERS)
        )
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters for the selected scraper, such as url, keyword, or page_turning.",
    )
    max_wait_seconds: int = Field(
        default=300,
        ge=1,
        le=300,
        description="Maximum total wait time for the remote task, in seconds.",
    )
    include_errors: bool = Field(
        default=True,
        description="Keep scraper records that contain an error marker.",
    )
    file_name: str = Field(
        default="{{TasksID}}",
        min_length=1,
        description="Remote result file name used by the builder endpoint.",
    )

    @field_validator("max_wait_seconds", mode="before")
    @classmethod
    def validate_max_wait(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("max_wait_seconds must be an integer between 1 and 300")
        return value


class ThorDataWebScraperTool(BaseTool):
    """LangChain tool that runs one of ThorData's supported Web Scrapers."""

    name: str = "thordata_web_scraper"
    description: str = (
        "Run one of seven supported ThorData Web Scrapers, wait for the final JSON records, "
        "and return those records."
    )
    args_schema: type[BaseModel] = ThorDataWebScraperInput
    client: ThorDataClient = Field(exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(
        self,
        *,
        client: ThorDataClient | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> None:
        resolved_client = client or ThorDataClient(
            api_key=api_key,
            timeout=timeout,
        )
        super().__init__(client=resolved_client, **kwargs)

    def _run(
        self,
        spider_id: WebScraperId,
        params: dict[str, Any] | None = None,
        max_wait_seconds: int = 300,
        include_errors: bool = True,
        file_name: str = "{{TasksID}}",
        run_manager: CallbackManagerForToolRun | None = None,
    ) -> str:
        del run_manager
        result = self.client.scrape(
            spider_id,
            params,
            max_wait_seconds=max_wait_seconds,
            include_errors=include_errors,
            file_name=file_name,
        )
        return self._serialize(result)

    async def _arun(
        self,
        spider_id: WebScraperId,
        params: dict[str, Any] | None = None,
        max_wait_seconds: int = 300,
        include_errors: bool = True,
        file_name: str = "{{TasksID}}",
        run_manager: AsyncCallbackManagerForToolRun | None = None,
    ) -> str:
        del run_manager
        result = await self.client.ascrape(
            spider_id,
            params,
            max_wait_seconds=max_wait_seconds,
            include_errors=include_errors,
            file_name=file_name,
        )
        return self._serialize(result)

    @staticmethod
    def _serialize(result: Any) -> str:
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
