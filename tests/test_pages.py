import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.sample import seed
from app.store import Store


@pytest.fixture
def client():
    return TestClient(create_app(Store()))


def make(client, **body):
    res = client.post("/api/pages", json=body)
    assert res.status_code == 201
    return res.json()


def test_create_and_read_a_page(client):
    page = make(client, title="Ideas", body="# One\n\nTwo")
    got = client.get(f"/api/pages/{page['id']}").json()
    assert got["title"] == "Ideas"
    assert got["body"] == "# One\n\nTwo"
    assert got["favorite"] is False


def test_missing_page_is_404(client):
    assert client.get("/api/pages/999").status_code == 404
    assert client.patch("/api/pages/999", json={"title": "x"}).status_code == 404
    assert client.delete("/api/pages/999").status_code == 404


def test_pages_nest_in_the_tree(client):
    parent = make(client, title="Product")
    child = make(client, title="Roadmap", parent_id=parent["id"])
    tree = client.get("/api/pages").json()["pages"]
    assert [p["title"] for p in tree] == ["Product"]
    assert tree[0]["children"][0]["id"] == child["id"]


def test_child_of_a_missing_parent_is_refused(client):
    assert client.post("/api/pages", json={"parent_id": 42}).status_code == 404


def test_update_changes_only_what_is_sent(client):
    page = make(client, title="Draft", body="keep me")
    got = client.patch(f"/api/pages/{page['id']}", json={"title": "Final"}).json()
    assert got["title"] == "Final"
    assert got["body"] == "keep me"


def test_a_page_cannot_move_inside_its_own_child(client):
    parent = make(client, title="A")
    child = make(client, title="B", parent_id=parent["id"])
    res = client.patch(f"/api/pages/{parent['id']}", json={"parent_id": child["id"]})
    assert res.status_code == 400


def test_favourites_are_listed(client):
    page = make(client, title="Pinned")
    make(client, title="Not pinned")
    client.patch(f"/api/pages/{page['id']}", json={"favorite": True})
    favorites = client.get("/api/pages").json()["favorites"]
    assert [f["title"] for f in favorites] == ["Pinned"]


def test_deleting_a_page_deletes_its_children(client):
    parent = make(client, title="Old")
    child = make(client, title="Older", parent_id=parent["id"])
    assert client.delete(f"/api/pages/{parent['id']}").status_code == 204
    assert client.get(f"/api/pages/{child['id']}").status_code == 404


def test_search_matches_title_and_body(client):
    make(client, title="Standup notes", body="nothing here")
    make(client, title="Handbook", body="Our standup is at ten")
    results = client.get("/api/search", params={"q": "standup"}).json()["results"]
    assert [r["title"] for r in results] == ["Standup notes", "Handbook"]
    assert "standup is at ten" in results[1]["snippet"]


def test_empty_search_returns_nothing(client):
    make(client, title="Anything")
    assert client.get("/api/search", params={"q": "  "}).json()["results"] == []


def test_sample_pages_fill_a_new_workspace():
    store = Store()
    seed(store)
    titles = [p["title"] for p in store.tree()]
    assert "Getting started" in titles
    assert store.favorites()


def test_the_app_page_is_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Fernpage" in res.text
