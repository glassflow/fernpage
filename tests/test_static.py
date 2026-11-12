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
