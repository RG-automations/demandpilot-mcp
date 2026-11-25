"""Real MCP client/server integration tests (SPECIFICATION.md section 10.5).

The server always runs as a real subprocess (`python -m demandpilot --db ...`)
communicating over actual stdio, driven by the official `mcp` client
(`ClientSession` + `stdio_client`) - never called in-process. Every test is
time-bounded so a misbehaving subprocess cannot hang the suite.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

EXPECTED_TOOLS = {
    "get_sales_history",
    "forecast_demand",
    "get_inventory",
    "detect_stockout_risk",
    "recommend_replenishment",
}
TIMEOUT_SECONDS = 30


async def _with_session(db_path: Path, fn):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "demandpilot", "--db", str(db_path)]
    )
    with anyio.fail_after(TIMEOUT_SECONDS):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(session)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_session_initializes_and_terminates_cleanly(demo_db_path):
    async def go(session):
        return True

    assert anyio.run(_with_session, demo_db_path, go) is True


def test_exactly_five_tools_are_discovered(demo_db_path):
    async def go(session):
        result = await session.list_tools()
        return {t.name for t in result.tools}

    names = anyio.run(_with_session, demo_db_path, go)
    assert names == EXPECTED_TOOLS
    assert len(names) == 5


def test_catalog_resource_is_discovered_and_readable(demo_db_path):
    async def go(session):
        resources = await session.list_resources()
        assert any(str(r.uri) == "demandpilot://catalog" for r in resources.resources)
        read = await session.read_resource("demandpilot://catalog")
        return read.contents[0].text

    text = anyio.run(_with_session, demo_db_path, go)
    data = json.loads(text)
    assert data["is_synthetic"] is True
    assert data["seed"] == 42
    assert len(data["products"]) == 20


def test_prompt_is_discovered_and_fetchable(demo_db_path):
    async def go(session):
        prompts = await session.list_prompts()
        assert any(p.name == "weekly-replenishment-report" for p in prompts.prompts)
        result = await session.get_prompt("weekly-replenishment-report")
        return result.messages[0].content.text

    text = anyio.run(_with_session, demo_db_path, go)
    assert "stockout" in text.lower()
    assert "recommend_replenishment" in text


def test_get_sales_history_tool_call(demo_db_path):
    async def go(session):
        return await session.call_tool("get_sales_history", {"sku": "DEMO-001", "days": 30})

    result = anyio.run(_with_session, demo_db_path, go)
    assert result.is_error is False
    data = json.loads(result.content[0].text)
    assert data["sku"] == "DEMO-001"
    assert data["returned_days"] <= 30


def test_forecast_demand_tool_call(demo_db_path):
    async def go(session):
        return await session.call_tool("forecast_demand", {"sku": "DEMO-002", "horizon_days": 14})

    result = anyio.run(_with_session, demo_db_path, go)
    assert result.is_error is False
    data = json.loads(result.content[0].text)
    assert data["horizon_days"] == 14
    assert len(data["daily_forecast"]) == 14
    assert data["model_used"] in {
        "holt_winters",
        "seasonal_naive",
        "historical_mean",
        "zero_demand",
        "insufficient_history",
    }


def test_get_inventory_tool_call(demo_db_path):
    async def go(session):
        return await session.call_tool("get_inventory", {"sku": "DEMO-001"})

    result = anyio.run(_with_session, demo_db_path, go)
    assert result.is_error is False
    data = json.loads(result.content[0].text)
    assert data["inventory_position"] == data["on_hand"] + data["on_order"] - data["reserved"]


def test_detect_stockout_risk_tool_call(demo_db_path):
    async def go(session):
        return await session.call_tool("detect_stockout_risk", {"horizon_days": 14})

    result = anyio.run(_with_session, demo_db_path, go)
    assert result.is_error is False
    data = json.loads(result.content[0].text)
    assert data["products_analyzed"] == 20
    assert all("risk_level" in r for r in data["results"])


def test_recommend_replenishment_tool_call(demo_db_path):
    async def go(session):
        return await session.call_tool("recommend_replenishment", {"sku": "DEMO-003"})

    result = anyio.run(_with_session, demo_db_path, go)
    assert result.is_error is False
    data = json.loads(result.content[0].text)
    assert data["final_order_qty"] >= 0
    assert data["final_order_qty"] % max(data["pack_size"], 1) == 0 or data["final_order_qty"] == 0


def test_nonexistent_sku_returns_domain_error_not_crash(demo_db_path):
    async def go(session):
        return await session.call_tool("get_inventory", {"sku": "DEMO-999"})

    result = anyio.run(_with_session, demo_db_path, go)
    assert result.is_error is True
    assert "SKU_NOT_FOUND" in result.content[0].text


def test_invalid_horizon_argument_is_rejected(demo_db_path):
    async def go(session):
        return await session.call_tool("forecast_demand", {"sku": "DEMO-001", "horizon_days": 999})

    result = anyio.run(_with_session, demo_db_path, go)
    assert result.is_error is True


def test_days_limit_is_enforced(demo_db_path):
    async def go(session):
        return await session.call_tool("get_sales_history", {"sku": "DEMO-001", "days": 10_000})

    result = anyio.run(_with_session, demo_db_path, go)
    assert result.is_error is True


def test_process_survives_a_tool_error_and_keeps_serving(demo_db_path):
    async def go(session):
        bad = await session.call_tool("get_inventory", {"sku": "DEMO-999"})
        good = await session.call_tool("get_inventory", {"sku": "DEMO-001"})
        return bad, good

    bad, good = anyio.run(_with_session, demo_db_path, go)
    assert bad.is_error is True
    assert good.is_error is False


def test_mcp_tools_never_modify_the_database(demo_db_path):
    before = _file_sha256(demo_db_path)

    async def go(session):
        for name, args in [
            ("get_sales_history", {"sku": "DEMO-001", "days": 30}),
            ("forecast_demand", {"sku": "DEMO-002", "horizon_days": 14}),
            ("get_inventory", {"sku": "DEMO-003"}),
            ("detect_stockout_risk", {"horizon_days": 14}),
            ("recommend_replenishment", {"sku": "DEMO-004"}),
        ]:
            await session.call_tool(name, args)

    anyio.run(_with_session, demo_db_path, go)
    after = _file_sha256(demo_db_path)
    assert before == after
