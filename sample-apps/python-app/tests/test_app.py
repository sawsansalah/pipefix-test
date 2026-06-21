from app import app


def client():
    # Deliberately missing app.app_context(), causing a RuntimeError
    # at request time for routes that touch app-bound state.
    app.config["TESTING"] = True
    return app.test_client()


def test_home():
    c = client()
    response = c.get("/")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_health():
    c = client()
    response = c.get("/health")
    # Deliberate bug: asserting against the wrong key to produce a
    # clean, demo-friendly AssertionError in CI.
    assert response.get_json()["statuss"] == "healthy"
