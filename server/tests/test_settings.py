from fastapi.testclient import TestClient


def test_defaults(authed: TestClient) -> None:
    data = authed.get("/api/settings").json()
    assert data["raw"] == "{}"
    assert data["effective"]["workbench.theme"] == "dark"
    assert data["effective"]["editor.fontSize"] == 14
    assert "properties" in data["json_schema"]


def test_save_keeps_raw_text_and_merges(authed: TestClient) -> None:
    raw = '{\n  "editor.fontSize": 16\n}'
    data = authed.put("/api/settings", json={"raw": raw}).json()
    assert data["raw"] == raw
    assert data["effective"]["editor.fontSize"] == 16
    assert data["effective"]["editor.tabSize"] == 4
    assert authed.get("/api/settings").json()["raw"] == raw


def test_rejects_invalid(authed: TestClient) -> None:
    assert authed.put("/api/settings", json={"raw": "{nope"}).status_code == 422
    resp = authed.put("/api/settings", json={"raw": '{"editor.fontSize": "big"}'})
    assert resp.status_code == 422
    assert "editor.fontSize" in resp.json()["detail"]
    assert authed.put("/api/settings", json={"raw": '{"unknown.key": 1}'}).status_code == 422


def test_themes(authed: TestClient) -> None:
    themes = {t["id"]: t for t in authed.get("/api/themes").json()}
    assert {
        "dark",
        "light",
        "high-contrast",
        "solarized-dark",
        "solarized-light",
        "monokai",
        "github-dark",
        "nord",
    } <= themes.keys()
    assert themes["light"]["colors"]["editor.background"] == "#ffffff"
    assert themes["solarized-light"]["type"] == "light"


def test_themes_define_the_same_keys(authed: TestClient) -> None:
    themes = authed.get("/api/themes").json()
    reference = next(t for t in themes if t["id"] == "dark")
    for theme in themes:
        assert theme["colors"].keys() == reference["colors"].keys(), theme["id"]
        assert len(theme["tokenColors"]) == len(reference["tokenColors"]), theme["id"]
