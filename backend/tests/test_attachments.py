"""Private conversation attachments: storage consistency and tenant isolation."""

import base64

import pytest

from app import attachments as attachment_service
from app import main
from conftest import TENANT_ORIGIN

ADMIN = {"Authorization": "Bearer test-admin"}
PIXEL = b"\x89PNG\r\n\x1a\n fake image bytes"


def _conversation(client, tenant, visitor="attachment-test"):
    return client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": visitor, "message": "ciao"}
    ).json()


def _other_tenant(client):
    other = client.post("/admin/clients", headers=ADMIN, json={"name": "Attachment Other", "allowed_origins": TENANT_ORIGIN}).json()
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


def _channel_key(client, tenant):
    created = client.post(
        "/api-keys", headers=tenant["op"], json={"name": "Channel adapter", "scopes": ["channels:write"]}
    )
    assert created.status_code == 200
    return {"Authorization": f"Bearer {created.json()['token']}"}


def _media(data=PIXEL, filename="foto.jpg", content_type="image/jpeg"):
    return {"filename": filename, "content_type": content_type, "data": base64.b64encode(data).decode()}


def _whatsapp(**overrides):
    payload = {"from_number": "+393331234567", "text": "Ecco la foto", "message_id": "wamid.media-1"}
    payload.update(overrides)
    return payload


def test_inbound_channel_media_is_stored_privately_and_reaches_the_operator(client, tenant, monkeypatch):
    objects = _storage(monkeypatch)
    headers = _channel_key(client, tenant)
    inbound = client.post(
        "/channels/whatsapp/inbound", headers=headers,
        json=_whatsapp(attachments=[_media(), _media(data=b"scontrino", filename="ricevuta.pdf", content_type="application/pdf")]),
    )
    assert inbound.status_code == 200
    conv_id = inbound.json()["conversation_id"]
    assert len(objects) == 2

    message = client.get(f"/conversations/{conv_id}/messages", headers=tenant["op"]).json()["messages"][-1]
    assert message["content"] == "Ecco la foto\nAllegati: foto.jpg, ricevuta.pdf"
    assert [a["content_type"] for a in message["attachments"]] == ["image/jpeg", "application/pdf"]

    downloaded = client.get(f"/attachments/{message['attachments'][0]['id']}", headers=tenant["op"])
    assert downloaded.status_code == 200 and downloaded.content == PIXEL
    # the private bytes stay behind the operator session: no public URL is ever created
    assert all(key.startswith(f"tenant/{tenant['cid']}/conversation/{conv_id}/") for key in objects)


def test_media_only_message_is_accepted_on_every_channel(client, tenant, monkeypatch):
    _storage(monkeypatch)
    headers = _channel_key(client, tenant)
    whatsapp = client.post(
        "/channels/whatsapp/inbound", headers=headers,
        json=_whatsapp(text="", message_id="wamid.media-only", attachments=[_media()]),
    )
    assert whatsapp.status_code == 200
    email = client.post(
        "/channels/email/inbound", headers=headers,
        json={"from_email": "mario@example.it", "subject": "Foto", "text": "", "message_id": "<media@example.it>",
              "attachments": [_media()]},
    )
    assert email.status_code == 200
    meta = client.post(
        "/channels/meta/inbound", headers=headers,
        json={"platform": "messenger", "sender_id": "psid-1", "text": "", "message_id": "mid.media",
              "attachments": [_media()]},
    )
    assert meta.status_code == 200

    thread = client.get(f"/conversations/{whatsapp.json()['conversation_id']}/messages", headers=tenant["op"]).json()
    assert thread["messages"][-1]["content"] == "Allegato: foto.jpg"


def test_empty_message_without_media_is_still_refused(client, tenant, monkeypatch):
    _storage(monkeypatch)
    headers = _channel_key(client, tenant)
    refused = client.post("/channels/whatsapp/inbound", headers=headers, json=_whatsapp(text=""))
    assert refused.status_code == 400


@pytest.mark.parametrize(
    "attachments,status",
    [
        ([{"filename": "x.jpg", "content_type": "image/jpeg", "data": "not base64!"}], 400),
        ([{"filename": "x.exe", "content_type": "application/octet-stream", "data": "ZGF0YQ=="}], 415),
        ([{"filename": "x.jpg", "content_type": "image/jpeg", "data": ""}], 400),
    ],
)
def test_malformed_adapter_media_is_refused_whole(client, tenant, monkeypatch, attachments, status):
    objects = _storage(monkeypatch)
    headers = _channel_key(client, tenant)
    refused = client.post(
        "/channels/whatsapp/inbound", headers=headers, json=_whatsapp(attachments=attachments)
    )
    assert refused.status_code == status
    # nothing is half-stored: no object, no conversation
    assert objects == {}
    assert client.get("/conversations", headers=tenant["op"]).json() == []


def test_storage_outage_keeps_the_customer_message(client, tenant, monkeypatch):
    _storage(monkeypatch)
    monkeypatch.setattr(main.attachment_service, "put", lambda *_args: False)
    headers = _channel_key(client, tenant)
    inbound = client.post(
        "/channels/whatsapp/inbound", headers=headers, json=_whatsapp(attachments=[_media()])
    )
    assert inbound.status_code == 200
    message = client.get(
        f"/conversations/{inbound.json()['conversation_id']}/messages", headers=tenant["op"]
    ).json()["messages"][-1]
    assert message["content"] == "Ecco la foto\n[1 allegato non salvato]"
    assert message["attachments"] == []


def test_unconfigured_storage_never_drops_an_inbound_message(client, tenant, monkeypatch):
    monkeypatch.setattr(main.attachment_service, "configured", lambda: False)
    headers = _channel_key(client, tenant)
    inbound = client.post(
        "/channels/whatsapp/inbound", headers=headers, json=_whatsapp(text="", attachments=[_media()])
    )
    assert inbound.status_code == 200
    message = client.get(
        f"/conversations/{inbound.json()['conversation_id']}/messages", headers=tenant["op"]
    ).json()["messages"][-1]
    assert message["content"] == "[1 allegato non salvato]"


def test_inbound_media_limits(monkeypatch):
    monkeypatch.setattr(attachment_service, "MAX_INBOUND_FILES", 2)
    monkeypatch.setattr(attachment_service, "MAX_BYTES", 8)
    monkeypatch.setattr(attachment_service, "MAX_INBOUND_TOTAL_BYTES", 12)
    small = _media(data=b"1234", filename="a.jpg")

    assert len(attachment_service.decode_inbound([small, small])) == 2
    assert attachment_service.decode_inbound(None) == []

    for payload in ("nope", [42]):
        with pytest.raises(attachment_service.InboundMediaError) as shape:
            attachment_service.decode_inbound(payload)
        assert shape.value.status == 400

    over_cap = [_media(data=b"1234567", filename="b.jpg"), _media(data=b"1234567", filename="c.jpg")]
    for payload, status in (
        ([small, small, small], 400),                          # more files than allowed
        ([_media(data=b"123456789", filename="b.jpg")], 413),   # one file over the per-file cap
        (over_cap, 413),                                       # each file fits, the message does not
    ):
        with pytest.raises(attachment_service.InboundMediaError) as failure:
            attachment_service.decode_inbound(payload)
        assert failure.value.status == status


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
