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


def _fn(js, head):
    """Source of one top-level function, from its header to the closing brace at column 0."""
    return js.split(head)[1].split("\n}\n")[0]


def test_source_every_comment_action_goes_through_act(client):
    # Source check only: Delete, Resolve, Reply and a new comment all call act(), and act() reloads
    # the list after the failure is caught and shows the error only for the page it came from.
    js = _app_js(client)
    assert js.count("await act(") >= 4
    act = _fn(js, "async function act(")
    assert "catch (e)" in act and "failure = e" in act
    assert act.index("catch (e)") < act.index("await loadComments(snap)")
    assert "current.id === pageId) showCommentError(failure)" in act
    # none of the actions shows an error or reloads on its own any more
    for head in ("del.onclick = async", "btn.onclick = async"):
        assert "showCommentError" not in js.split(head)[1].split("};")[0]


def test_source_load_is_sequenced_and_the_page_is_checked_twice(client):
    js = _app_js(client)
    load = _fn(js, "async function loadComments(")
    assert "const seq = ++loadSeq" in load
    # the error path and the success path both drop an answer that is no longer the newest
    assert load.count("seq === loadSeq") + load.count("seq !== loadSeq") == 2
    assert "loadSeq++" in _fn(js, "function clearComments()")


def test_source_reply_drafts_and_labels(client):
    js = _app_js(client)
    reply = _fn(js, "function replyForm(")
    assert "box.value = drafts.get(t.id)" in reply
    assert 'addEventListener("input"' in reply and "drafts.set(t.id, box.value)" in reply
    assert "box.setAttribute(\"aria-labelledby\"" in reply
    assert 'del.setAttribute("aria-labelledby"' in js
    assert '"aria-label", openThreads.length' in js
    html = client.get("/").text
    assert 'id="author" aria-label=' in html and 'id="comment-body" aria-label=' in html
