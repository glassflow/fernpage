import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.store import Store


@pytest.fixture
def client():
    return TestClient(create_app(Store()))


def make(client, **body):
    res = client.post("/api/pages", json=body)
    assert res.status_code == 201
    return res.json()


def comment(client, page_id, body="hi", author=""):
    res = client.post(f"/api/pages/{page_id}/comments", json={"body": body, "author": author})
    assert res.status_code == 201
    return res.json()


def test_add_and_list_thread(client):
    page = make(client, title="Notes")
    res = client.post(
        f"/api/pages/{page['id']}/comments", json={"body": "**hello**", "author": "Ann"}
    )
    assert res.status_code == 201
    thread = res.json()
    assert thread["author"] == "Ann"
    assert thread["body"] == "**hello**"
    assert thread["page_id"] == page["id"]
    assert thread["resolved"] is False
    assert thread["resolved_at"] is None
    assert thread["replies"] == []
    listed = client.get(f"/api/pages/{page['id']}/comments")
    assert listed.status_code == 200
    assert listed.json() == {"threads": [thread]}


def test_blank_author_is_anonymous(client):
    page = make(client, title="Notes")
    assert comment(client, page["id"], author="   ")["author"] == "Anonymous"
    assert comment(client, page["id"])["author"] == "Anonymous"


def test_empty_comment_is_400(client):
    page = make(client, title="Notes")
    res = client.post(f"/api/pages/{page['id']}/comments", json={"body": "   "})
    assert res.status_code == 400
    assert res.json()["detail"] == "a comment needs some text"
    thread = comment(client, page["id"])
    res = client.post(f"/api/comments/{thread['id']}/replies", json={"body": " \n"})
    assert res.status_code == 400


def test_missing_body_is_422(client):
    page = make(client, title="Notes")
    assert client.post(f"/api/pages/{page['id']}/comments", json={}).status_code == 422
    assert client.post(f"/api/pages/{page['id']}/comments", json={"body": 5}).status_code == 422


def test_comments_on_missing_page_is_404(client):
    res = client.get("/api/pages/999/comments")
    assert (res.status_code, res.json()["detail"]) == (404, "no such page")
    res = client.post("/api/pages/999/comments", json={"body": "hi"})
    assert (res.status_code, res.json()["detail"]) == (404, "no such page")


def test_reply_appears_in_thread(client):
    page = make(client, title="Notes")
    thread = comment(client, page["id"])
    res = client.post(
        f"/api/comments/{thread['id']}/replies", json={"body": "right", "author": "Bo"}
    )
    assert res.status_code == 201
    reply = res.json()
    assert reply["parent_id"] == thread["id"]
    assert reply["page_id"] == page["id"]
    assert reply["author"] == "Bo"
    threads = client.get(f"/api/pages/{page['id']}/comments").json()["threads"]
    assert threads[0]["replies"] == [reply]


def test_reply_to_reply_is_400(client):
    page = make(client, title="Notes")
    thread = comment(client, page["id"])
    reply = client.post(f"/api/comments/{thread['id']}/replies", json={"body": "hi"}).json()
    res = client.post(f"/api/comments/{reply['id']}/replies", json={"body": "deeper"})
    assert res.status_code == 400
    assert res.json()["detail"] == "replies are one level deep"


def test_reply_to_missing_comment_is_404(client):
    res = client.post("/api/comments/999/replies", json={"body": "hi"})
    assert (res.status_code, res.json()["detail"]) == (404, "no such comment")


def test_resolve_and_reopen_thread(client):
    page = make(client, title="Notes")
    thread = comment(client, page["id"])
    res = client.patch(f"/api/comments/{thread['id']}", json={"resolved": True})
    assert res.status_code == 200
    assert res.json()["resolved"] is True
    assert res.json()["resolved_at"]
    res = client.patch(f"/api/comments/{thread['id']}", json={"resolved": False})
    assert res.status_code == 200
    assert res.json()["resolved"] is False
    assert res.json()["resolved_at"] is None


def test_resolving_a_reply_is_400(client):
    page = make(client, title="Notes")
    thread = comment(client, page["id"])
    reply = client.post(f"/api/comments/{thread['id']}/replies", json={"body": "hi"}).json()
    res = client.patch(f"/api/comments/{reply['id']}", json={"resolved": True})
    assert res.status_code == 400
    assert res.json()["detail"] == "only a thread can be resolved"


def test_resolve_missing_comment_is_404(client):
    res = client.patch("/api/comments/999", json={"resolved": True})
    assert (res.status_code, res.json()["detail"]) == (404, "no such comment")


def test_delete_comment_and_missing_is_404(client):
    page = make(client, title="Notes")
    thread = comment(client, page["id"])
    assert client.delete(f"/api/comments/{thread['id']}").status_code == 204
    res = client.delete(f"/api/comments/{thread['id']}")
    assert (res.status_code, res.json()["detail"]) == (404, "no such comment")
    assert client.get(f"/api/pages/{page['id']}/comments").json() == {"threads": []}


def test_delete_thread_deletes_replies(client):
    page = make(client, title="Notes")
    thread = comment(client, page["id"])
    reply = client.post(f"/api/comments/{thread['id']}/replies", json={"body": "hi"}).json()
    assert client.delete(f"/api/comments/{thread['id']}").status_code == 204
    assert client.delete(f"/api/comments/{reply['id']}").status_code == 404


def test_page_delete_removes_comments(client):
    page = make(client, title="Notes")
    thread = comment(client, page["id"])
    assert client.delete(f"/api/pages/{page['id']}").status_code == 204
    assert client.get(f"/api/pages/{page['id']}/comments").status_code == 404
    assert client.delete(f"/api/comments/{thread['id']}").status_code == 404


def test_open_comments_on_page(client):
    page = make(client, title="Notes")
    assert client.get(f"/api/pages/{page['id']}").json()["open_comments"] == 0
    first = comment(client, page["id"], "one")
    second = comment(client, page["id"], "two")
    client.post(f"/api/comments/{first['id']}/replies", json={"body": "reply"})
    client.patch(f"/api/comments/{second['id']}", json={"resolved": True})
    assert client.get(f"/api/pages/{page['id']}").json()["open_comments"] == 1
