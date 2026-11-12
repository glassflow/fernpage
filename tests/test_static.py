import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.store import Store


@pytest.fixture
def client():
    return TestClient(create_app(Store()))


def test_index_has_comment_elements(client):
    res = client.get("/")
    assert res.status_code == 200
    for ident in (
        "comments",
        "threads",
        "new-comment",
        "author",
        "comment-body",
        "resolved",
        "resolved-threads",
        "comments-error",
    ):
        assert f'id="{ident}"' in res.text


def _app_js(client):
    res = client.get("/static/app.js")
    assert res.status_code == 200
    return res.text


def test_app_js_wires_reply_and_delete(client):
    js = _app_js(client)
    assert '"/api/comments/" + t.id + "/replies"' in js
    assert 'api("DELETE", "/api/comments/" + c.id)' in js
    # resolved threads get no reply form
    assert "if (!t.resolved) div.append(replyForm(t))" in js


def test_app_js_comment_bodies_use_markdown_styles(client):
    assert 'div.className = "comment-body markdown"' in _app_js(client)


def test_app_js_has_no_dialogs(client):
    js = _app_js(client)
    for call in ("alert(", "confirm(", "prompt("):
        assert call not in js


def test_app_js_guards_double_submit_and_stale_pages(client):
    js = _app_js(client)
    assert js.count("once(") >= 3  # definition, new-comment form, reply form
    assert "if (current && current.id === pageId) showCommentError(e)" in js
    assert js.count("clearComments();") >= 2  # on switching pages, and when the new page is set
