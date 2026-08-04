"""Proactive widget messages: configuration, public payload, counters and tenant isolation."""
from sqlmodel import Session

from app import db

ADMIN = {"Authorization": "Bearer test-admin"}


def _rule(client, tenant, **overrides):
    payload = {
        "name": "Aiuto sul carrello",
        "message": "Posso aiutarti a completare l'ordine?",
        "trigger_type": "cart",
        "frequency": "once_per_day",
    }
    payload.update(overrides)
    return client.post("/proactive-rules", headers=tenant["op"], json=payload)


def _other_tenant(client, name="Proactive Other"):
    other = client.post("/admin/clients", headers=ADMIN, json={"name": name}).json()
    email = f"{name.lower().replace(' ', '-')}@other.it"
    client.post(
        f"/admin/clients/{other['id']}/operators", headers=ADMIN, json={"email": email, "password": "password1"}
    )
    token = client.post("/operator/login", json={"email": email, "password": "password1"}).json()["token"]
    return {
        "cid": other["id"],
        "key": {"Authorization": f"Bearer {other['api_key']}"},
        "op": {"Authorization": f"Bearer {token}"},
    }


def test_create_and_list_rules(client, tenant):
    created = _rule(client, tenant).json()
    assert created["trigger_type"] == "cart"
    assert created["engagement_rate"] is None  # nessun dato ancora

    listed = client.get("/proactive-rules", headers=tenant["op"]).json()
    assert listed["triggers"] == ["url", "time_on_page", "exit_intent", "cart"]
    assert [r["id"] for r in listed["rules"]] == [created["id"]]


def test_validation(client, tenant):
    assert _rule(client, tenant, name="  ").status_code == 400
    assert _rule(client, tenant, message="  ").status_code == 400
    assert _rule(client, tenant, trigger_type="telepatia").status_code == 400
    assert _rule(client, tenant, frequency="sempre e comunque").status_code == 400
    assert client.get("/proactive-rules", headers=tenant["op"]).json()["rules"] == []


def test_delay_is_bounded_and_message_capped(client, tenant):
    created = _rule(client, tenant, trigger_type="time_on_page", delay_seconds=999999, message="x" * 500).json()
    assert created["delay_seconds"] == 3600
    assert len(created["message"]) == 300


def test_widget_gets_only_active_rules_and_nothing_internal(client, tenant):
    active = _rule(client, tenant, name="Attiva").json()
    inactive = _rule(client, tenant, name="Spenta", active=False).json()

    payload = client.get("/widget/proactive", headers=tenant["key"]).json()
    assert [r["id"] for r in payload["rules"]] == [active["id"]]
    assert inactive["id"] not in [r["id"] for r in payload["rules"]]
    # il payload pubblico porta solo ciò che serve al browser per decidere
    assert set(payload["rules"][0]) == {
        "id", "trigger_type", "url_pattern", "delay_seconds", "message", "message_b", "frequency"
    }


def test_widget_endpoint_requires_the_client_key(client, tenant):
    _rule(client, tenant)
    assert client.get("/widget/proactive").status_code == 401
    assert client.get("/widget/proactive", headers={"Authorization": "Bearer non-esiste"}).status_code == 401


def test_counters_track_impressions_and_engagements(client, tenant):
    created = _rule(client, tenant).json()

    client.post(f"/widget/proactive/{created['id']}/event", headers=tenant["key"], json={"kind": "impression"})
    client.post(f"/widget/proactive/{created['id']}/event", headers=tenant["key"], json={"kind": "impression"})
    client.post(f"/widget/proactive/{created['id']}/event", headers=tenant["key"], json={"kind": "engagement"})

    rule = client.get("/proactive-rules", headers=tenant["op"]).json()["rules"][0]
    assert (rule["impressions"], rule["engagements"]) == (2, 1)
    assert rule["engagement_rate"] == 0.5

    assert client.post(
        f"/widget/proactive/{created['id']}/event", headers=tenant["key"], json={"kind": "boh"}
    ).status_code == 400


def test_ab_variant_is_public_and_counted_separately(client, tenant):
    created = _rule(client, tenant, message_b="Hai bisogno di aiuto con il carrello?").json()
    public = client.get("/widget/proactive", headers=tenant["key"]).json()["rules"][0]
    assert public["message_b"] == "Hai bisogno di aiuto con il carrello?"

    endpoint = f"/widget/proactive/{created['id']}/event"
    assert client.post(endpoint, headers=tenant["key"], json={"kind": "impression", "variant": "b"}).status_code == 200
    assert client.post(endpoint, headers=tenant["key"], json={"kind": "engagement", "variant": "b"}).status_code == 200
    rule = client.get("/proactive-rules", headers=tenant["op"]).json()["rules"][0]
    assert (rule["impressions_b"], rule["engagements_b"], rule["engagement_rate_b"]) == (1, 1, 1.0)
    assert (rule["impressions"], rule["engagements"]) == (0, 0)


def test_variant_b_requires_a_configured_message(client, tenant):
    created = _rule(client, tenant).json()
    response = client.post(
        f"/widget/proactive/{created['id']}/event",
        headers=tenant["key"],
        json={"kind": "impression", "variant": "b"},
    )
    assert response.status_code == 400


def test_ab_test_waits_for_a_minimum_sample(client, tenant):
    created = _rule(client, tenant, message_b="Alternativa").json()
    assert created["ab_test"] == {
        "status": "collecting", "winner": None, "lift_percent": None, "remaining": 30,
    }


def test_ab_test_declares_only_a_statistically_significant_winner(client, tenant):
    created = _rule(client, tenant, message_b="Alternativa").json()
    with Session(db.engine) as session:
        rule = session.get(db.ProactiveRule, created["id"])
        rule.impressions, rule.engagements = 200, 60
        rule.impressions_b, rule.engagements_b = 200, 20
        session.add(rule)
        session.commit()

    result = client.get("/proactive-rules", headers=tenant["op"]).json()["rules"][0]["ab_test"]
    assert result["status"] == "winner"
    assert result["winner"] == "a"
    assert result["lift_percent"] == 200.0
    assert result["z_score"] >= 1.96


def test_ab_test_keeps_close_results_inconclusive(client, tenant):
    created = _rule(client, tenant, message_b="Alternativa").json()
    with Session(db.engine) as session:
        rule = session.get(db.ProactiveRule, created["id"])
        rule.impressions, rule.engagements = 100, 20
        rule.impressions_b, rule.engagements_b = 100, 18
        session.add(rule)
        session.commit()
    result = client.get("/proactive-rules", headers=tenant["op"]).json()["rules"][0]["ab_test"]
    assert result["status"] == "inconclusive"
    assert result["winner"] is None


def test_promote_winner_archives_experiment_and_resets_rule(client, tenant):
    created = _rule(client, tenant, message="Originale", message_b="Vincente").json()
    with Session(db.engine) as session:
        rule = session.get(db.ProactiveRule, created["id"])
        rule.impressions, rule.engagements = 200, 20
        rule.impressions_b, rule.engagements_b = 200, 60
        session.add(rule)
        session.commit()

    response = client.post(
        f"/proactive-rules/{created['id']}/experiment",
        headers=tenant["op"], json={"action": "promote"},
    )
    assert response.status_code == 200
    rule = response.json()["rule"]
    assert rule["message"] == "Vincente"
    assert rule["message_b"] == ""
    assert (rule["impressions"], rule["engagements"], rule["impressions_b"], rule["engagements_b"]) == (0, 0, 0, 0)

    history = client.get("/proactive-rules", headers=tenant["op"]).json()["experiments"]
    assert len(history) == 1
    assert history[0]["outcome"] == "promoted"
    assert history[0]["statistical_winner"] == "b"
    assert history[0]["selected_variant"] == "b"
    assert (history[0]["engagements_a"], history[0]["engagements_b"]) == (20, 60)


def test_stop_inconclusive_experiment_preserves_message_and_history(client, tenant):
    created = _rule(client, tenant, message="Resta", message_b="Alternativa").json()
    response = client.post(
        f"/proactive-rules/{created['id']}/experiment",
        headers=tenant["op"], json={"action": "stop"},
    )
    assert response.status_code == 200
    assert response.json()["rule"]["message"] == "Resta"
    history = client.get("/proactive-rules", headers=tenant["op"]).json()["experiments"]
    assert history[0]["outcome"] == "stopped"
    assert history[0]["selected_variant"] is None


def test_cannot_promote_without_significant_winner(client, tenant):
    created = _rule(client, tenant, message_b="Alternativa").json()
    assert client.post(
        f"/proactive-rules/{created['id']}/experiment",
        headers=tenant["op"], json={"action": "promote"},
    ).status_code == 409


def test_experiment_history_is_tenant_scoped(client, tenant):
    created = _rule(client, tenant, message_b="Alternativa").json()
    client.post(
        f"/proactive-rules/{created['id']}/experiment",
        headers=tenant["op"], json={"action": "stop"},
    )
    other = _other_tenant(client, "Experiment Other")
    assert client.get("/proactive-rules", headers=other["op"]).json()["experiments"] == []
    assert client.post(
        f"/proactive-rules/{created['id']}/experiment",
        headers=other["op"], json={"action": "stop"},
    ).status_code == 404


def test_rules_are_tenant_scoped(client, tenant):
    created = _rule(client, tenant).json()
    other = _other_tenant(client)

    assert client.get("/proactive-rules", headers=other["op"]).json()["rules"] == []
    assert client.get("/widget/proactive", headers=other["key"]).json()["rules"] == []
    assert client.patch(
        f"/proactive-rules/{created['id']}", headers=other["op"], json={"active": False}
    ).status_code == 404
    assert client.delete(f"/proactive-rules/{created['id']}", headers=other["op"]).status_code == 404
    assert client.post(
        f"/widget/proactive/{created['id']}/event", headers=other["key"], json={"kind": "impression"}
    ).status_code == 404


def test_update_and_delete(client, tenant):
    created = _rule(client, tenant).json()
    updated = client.patch(
        f"/proactive-rules/{created['id']}",
        headers=tenant["op"],
        json={"trigger_type": "url", "url_pattern": "/spedizioni", "message": "Domande sulla spedizione?"},
    ).json()
    assert updated["trigger_type"] == "url"
    assert updated["url_pattern"] == "/spedizioni"
    assert client.patch(
        f"/proactive-rules/{created['id']}", headers=tenant["op"], json={"message": "  "}
    ).status_code == 400

    assert client.delete(f"/proactive-rules/{created['id']}", headers=tenant["op"]).status_code == 200
    assert client.get("/widget/proactive", headers=tenant["key"]).json()["rules"] == []
