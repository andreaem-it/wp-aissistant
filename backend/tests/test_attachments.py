"""Private conversation attachments: storage consistency and tenant isolation."""

from app import main

ADMIN = {"Authorization": "Bearer test-admin"}


def _conversation(client, tenant, visitor="attachment-test"):
    return client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": visitor, "message": "ciao"}
    ).json()


def _other_tenant(client):
    other = client.post("/admin/clients", headers=ADMIN, json={"name": "Attachment Other"}).json()
    client.post(
        f"/admin/clients/{other['id']}/operators",
        headers=ADMIN,
        json={"email": "attachment-other@example.it", "password": "password1"},
    )
    token = client.post(
        "/operator/login", json={"email": "attachment-other@example.it", "password": "password1"}
    ).json()["token"]
    return {"op": {"Authorization": f"Bearer {token}"}}


def _storage(monkeypatch):
    objects = {}
    monkeypatch.setattr(main.attachment_service, "configured", lambda: True)
    monkeypatch.setattr(
        main.attachment_service,
        "put",
        lambda key, data, content_type: objects.setdefault(key, (data, content_type)) is not None,
    )
    monkeypatch.setattr(main.attachment_service, "get", lambda key: objects.get(key))
    monkeypatch.setattr(main.attachment_service, "delete", lambda key: objects.pop(key, None) is not None)
    return objects


def test_upload_list_download_and_delete(client, tenant, monkeypatch):
    objects = _storage(monkeypatch)
    conv_id = _conversation(client, tenant)["conversation_id"]
    uploaded = client.post(
        f"/conversations/{conv_id}/attachments",
        headers=tenant["op"],
        files={"file": ("scheda.txt", b"contenuto privato", "text/plain")},
    )
    assert uploaded.status_code == 201
    attachment = uploaded.json()
    assert attachment["filename"] == "scheda.txt"
    assert len(objects) == 1

    messages = client.get(f"/conversations/{conv_id}/messages", headers=tenant["op"]).json()["messages"]
    assert messages[-1]["attachments"][0]["id"] == attachment["id"]
    downloaded = client.get(f"/attachments/{attachment['id']}", headers=tenant["op"])
    assert downloaded.status_code == 200
    assert downloaded.content == b"contenuto privato"
    assert "scheda.txt" in downloaded.headers["content-disposition"]
    assert downloaded.headers["cache-control"] == "private, no-store"

    deleted = client.delete(f"/attachments/{attachment['id']}", headers=tenant["op"])
    assert deleted.status_code == 200
    assert objects == {}
    assert client.get(f"/attachments/{attachment['id']}", headers=tenant["op"]).status_code == 404


def test_attachment_is_tenant_scoped(client, tenant, monkeypatch):
    _storage(monkeypatch)
    conv_id = _conversation(client, tenant)["conversation_id"]
    attachment = client.post(
        f"/conversations/{conv_id}/attachments",
        headers=tenant["op"],
        files={"file": ("private.pdf", b"pdf", "application/pdf")},
    ).json()
    other = _other_tenant(client)
    assert client.get(f"/attachments/{attachment['id']}", headers=other["op"]).status_code == 404
    assert client.delete(f"/attachments/{attachment['id']}", headers=other["op"]).status_code == 404


def test_rejected_or_failed_upload_never_creates_a_message(client, tenant, monkeypatch):
    _storage(monkeypatch)
    conv_id = _conversation(client, tenant)["conversation_id"]
    before = client.get(f"/conversations/{conv_id}/messages", headers=tenant["op"]).json()["messages"]
    rejected = client.post(
        f"/conversations/{conv_id}/attachments",
        headers=tenant["op"],
        files={"file": ("payload.exe", b"bad", "application/octet-stream")},
    )
    assert rejected.status_code == 415
    monkeypatch.setattr(main.attachment_service, "put", lambda *_args: False)
    failed = client.post(
        f"/conversations/{conv_id}/attachments",
        headers=tenant["op"],
        files={"file": ("ok.txt", b"good", "text/plain")},
    )
    assert failed.status_code == 502
    after = client.get(f"/conversations/{conv_id}/messages", headers=tenant["op"]).json()["messages"]
    assert len(after) == len(before)


def test_delete_failure_keeps_metadata(client, tenant, monkeypatch):
    _storage(monkeypatch)
    conv_id = _conversation(client, tenant)["conversation_id"]
    attachment = client.post(
        f"/conversations/{conv_id}/attachments",
        headers=tenant["op"],
        files={"file": ("keep.txt", b"keep", "text/plain")},
    ).json()
    monkeypatch.setattr(main.attachment_service, "delete", lambda _key: False)
    assert client.delete(f"/attachments/{attachment['id']}", headers=tenant["op"]).status_code == 502
    assert client.get(f"/attachments/{attachment['id']}", headers=tenant["op"]).status_code == 200
