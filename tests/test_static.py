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
        "comment-count",
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


def test_app_js_wires_resolve_reopen_and_count(client):
    js = _app_js(client)
    assert 'api("PATCH", "/api/comments/" + t.id, { resolved: !t.resolved })' in js
    assert 't.resolved ? "Reopen" : "Resolve ✓"' in js
    # the count comes from the loaded thread list, hides at zero, and is cleared on page switch
    assert '$("comment-count").textContent = "💬 " + openThreads.length' in js
    assert '$("comment-count").hidden = openThreads.length === 0' in js
    assert 'current.open_comments' not in js
    assert 'scrollIntoView({ behavior: "smooth", block: "start" })' in js
    clear = js.split("function clearComments()")[1].split("\n}\n")[0]
    assert '$("comment-count").hidden = true' in clear


def test_hidden_rule_survives_and_count_sets_no_display(client):
    css = client.get("/static/style.css").text
    assert "[hidden] { display: none !important; }" in css
    rule = css.split(".comment-count {")[1].split("}")[0]
    assert "display" not in rule
