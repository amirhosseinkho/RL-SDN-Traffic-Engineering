"""Integration tests for the FastAPI endpoints."""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.database.session import create_tables, drop_tables


@pytest_asyncio.fixture(scope="module")
async def client():
    """Spin up test app with in-memory SQLite."""
    import os
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    await create_tables()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    await drop_tables()


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_create_linear_topology(client: AsyncClient) -> None:
    payload = {
        "topology_type": "linear",
        "num_switches": 4,
        "num_hosts": 4,
        "bandwidth": 100,
        "latency": 5,
        "loss": 0,
        "name": "test-linear",
    }
    resp = await client.post("/api/v1/topology/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["topology_type"] == "linear"
    assert data["num_switches"] == 4
    assert "id" in data


@pytest.mark.asyncio
async def test_list_topologies(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/topology/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_get_topology_graph(client: AsyncClient) -> None:
    # Create first
    payload = {
        "topology_type": "linear",
        "num_switches": 3,
        "num_hosts": 3,
        "bandwidth": 100,
        "latency": 5,
        "loss": 0,
        "name": "graph-test",
    }
    create_resp = await client.post("/api/v1/topology/", json=payload)
    topo_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/topology/{topo_id}/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) == 6  # 3 switches + 3 hosts


@pytest.mark.asyncio
async def test_topology_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/topology/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_metrics_summary_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/metrics/summary")
    # Might be 503 if collector not initialized in test, or 200 with empty data
    assert resp.status_code in (200, 503)


@pytest.mark.asyncio
async def test_flows_list(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/flows/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_training_sessions_list(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/rl/sessions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_fat_tree_topology_creation(client: AsyncClient) -> None:
    payload = {
        "topology_type": "fat_tree",
        "num_switches": 20,
        "num_hosts": 16,
        "bandwidth": 100,
        "latency": 5,
        "loss": 0,
        "k": 4,
        "name": "fat-tree-test",
    }
    resp = await client.post("/api/v1/topology/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["topology_type"] == "fat_tree"
    assert data["num_switches"] > 0


@pytest.mark.asyncio
async def test_copilot_query(client: AsyncClient) -> None:
    payload = {"query": "Why is latency increasing?", "include_context": False}
    resp = await client.post("/api/v1/copilot/query", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "response" in data
    assert len(data["response"]) > 10
