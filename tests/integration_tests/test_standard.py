"""LangChain's standard tools integration suite for ThorDataSearchTool.

These tests call the live ThorData SERP API, so they only run when
THORDATA_API_KEY is present in the environment.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from langchain_tests.integration_tests import ToolsIntegrationTests

from langchain_thordata import ThorDataSearchTool

pytestmark = pytest.mark.skipif(
    not os.getenv("THORDATA_API_KEY"),
    reason="THORDATA_API_KEY is not set; skipping live ThorData calls.",
)


class TestThorDataSearchToolIntegration(ToolsIntegrationTests):
    """Run the upstream tools suite against the live ThorData SERP API."""

    @property
    def tool_constructor(self) -> type[ThorDataSearchTool]:
        return ThorDataSearchTool

    @property
    def tool_constructor_params(self) -> dict[str, Any]:
        return {"api_key": os.environ["THORDATA_API_KEY"]}

    @property
    def tool_invoke_params_example(self) -> dict[str, Any]:
        return {"query": "LangChain ThorData"}
