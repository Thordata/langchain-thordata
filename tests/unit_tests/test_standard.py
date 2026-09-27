"""LangChain's standard tools test suite for ThorDataSearchTool."""

from __future__ import annotations

from typing import Any

from langchain_tests.unit_tests import ToolsUnitTests

from langchain_thordata import ThorDataSearchTool


class TestThorDataSearchToolStandard(ToolsUnitTests):
    """Run the upstream tools suite so the tool stays interface-compatible."""

    @property
    def tool_constructor(self) -> type[ThorDataSearchTool]:
        return ThorDataSearchTool

    @property
    def tool_constructor_params(self) -> dict[str, Any]:
        return {"api_key": "test-secret"}

    @property
    def tool_invoke_params_example(self) -> dict[str, Any]:
        return {"query": "LangChain ThorData"}
