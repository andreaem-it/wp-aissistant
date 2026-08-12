"""Advanced analytics: deflection, response times and knowledge-gap detection."""
import json
from datetime import datetime, timedelta

from sqlmodel import Session, select

from app import analytics, db
from conftest import TENANT_ORIGIN


ADMIN = {"Authorization": "Bearer test-admin"}


def _other_tenant(client, name="Analytics Other"):
    other = client.post("/admin/clients", headers=ADMIN, json={"name": name, "allowed_origins": TENANT_ORIGIN}).json()
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


def _chat(client, tenant, visitor, message="ciao"):
    return client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": visitor, "message": message}
    ).json()


def _log_turn(client_id, conversation_id, outcome, distance=None, message_id=None, created_at=None):
    """Write an AI response log directly: the gap detector reads these, and the fake LLM in the
    tests never produces the retrieval shapes we need to exercise."""
    retrieved = []
    if distance is not None:
        retrieved = [{"chunk_id": 1, "source": "site", "source_ref": "/x", "distance": distance, "selected": True}]
    with Session(db.engine) as session:
        row = db.AiResponseLog(
            client_id=client_id,
            conversation_id=conversation_id,
            message_id=message_id,
            outcome=outcome,
            retrieved=json.dumps(retrieved),
            created_at=created_at or datetime.utcnow(),
        )
        session.add(row)
        session.commit()


# ---- overview ----


def test_deflection_counts_conversations_without_an_operator(client, tenant):
    solo_ai = _chat(client, tenant, "ai-only")
    with_human = _chat(client, tenant, "human", message="vorrei un rimborso")
    client.post(
        f"/conversations/{with_human['conversation_id']}/reply",
        headers=tenant["op"], json={"reply": "ci penso io"},
    )

    overview = client.get("/analytics/overview", headers=tenant["op"]).json()
    assert overview["conversations"] == 2
    assert overview["handled_by_ai"] == 1
    assert overview["deflection_rate"] == 0.5
    assert overview["escalated"] == 1
    assert solo_ai["conversation_id"] != with_human["conversation_id"]


def test_overview_is_empty_without_data(client, tenant):
    overview = client.get("/analytics/overview", headers=tenant["op"]).json()
    assert overview["conversations"] == 0
    assert overview["deflection_rate"] is None
    assert overview["first_response"] == {"average_minutes": None, "median_minutes": None, "count": 0}
    assert overview["csat"]["average"] is None
    assert overview["trend"] == []


def test_first_response_and_resolution_times(client, tenant):
    chat = _chat(client, tenant, "timing", message="vorrei un rimborso")
    conv_id = chat["conversation_id"]
    with Session(db.engine) as session:
        conv = session.get(db.Conversation, conv_id)
        conv.created_at = datetime.utcnow() - timedelta(hours=2)
        conv.sla_started_at = datetime.utcnow() - timedelta(minutes=30)
        session.add(conv)
        session.commit()

    client.post(f"/conversations/{conv_id}/reply", headers=tenant["op"], json={"reply": "eccomi"})
    client.post(f"/conversations/{conv_id}/status", headers=tenant["op"], json={"status": "closed"})

    overview = client.get("/analytics/overview", headers=tenant["op"]).json()
    assert overview["first_response"]["count"] == 1
    assert 29 <= overview["first_response"]["average_minutes"] <= 31
    assert overview["resolution"]["count"] == 1
    assert 119 <= overview["resolution"]["average_minutes"] <= 121
    assert overview["closed"] == 1


def test_median_uses_the_middle_value(client, tenant):
    # tre conversazioni con prima risposta a 10, 20 e 60 minuti: media 30, mediana 20
    for index, minutes in enumerate((10, 20, 60)):
        chat = _chat(client, tenant, f"median-{index}", message="vorrei un rimborso")
        with Session(db.engine) as session:
            conv = session.get(db.Conversation, chat["conversation_id"])
            conv.sla_started_at = datetime.utcnow() - timedelta(minutes=minutes)
            conv.first_response_at = datetime.utcnow()
            session.add(conv)
            session.commit()

    stats = client.get("/analytics/overview", headers=tenant["op"]).json()["first_response"]
    assert stats["count"] == 3
    assert stats["average_minutes"] == 30.0
    assert stats["median_minutes"] == 20.0


def test_trend_series(client, tenant):
    _chat(client, tenant, "trend-1")
    _chat(client, tenant, "trend-2", message="vorrei un rimborso")

    trend = client.get("/analytics/overview", headers=tenant["op"]).json()["trend"]
    assert len(trend) == 1
    assert trend[0]["conversations"] == 2
    assert trend[0]["escalated"] == 1


def test_period_excludes_older_conversations(client, tenant):
    chat = _chat(client, tenant, "vecchia")
    with Session(db.engine) as session:
        conv = session.get(db.Conversation, chat["conversation_id"])
        conv.created_at = datetime.utcnow() - timedelta(days=60)
        session.add(conv)
        session.commit()

    assert client.get("/analytics/overview", headers=tenant["op"], params={"days": 30}).json()["conversations"] == 0
    assert client.get("/analytics/overview", headers=tenant["op"], params={"days": 90}).json()["conversations"] == 1


# ---- knowledge gaps ----


def test_gap_detected_when_the_ai_escalates_without_context(client, tenant):
    chat = _chat(client, tenant, "gap", message="Fate consegne in Svizzera?")
    _log_turn(tenant["cid"], chat["conversation_id"], "escalated_model", distance=0.9)

    payload = client.get("/analytics/knowledge-gaps", headers=tenant["op"]).json()
    assert payload["total"] == 1
    gap = payload["gaps"][0]
    assert gap["question"] == "Fate consegne in Svizzera?"
    assert gap["occurrences"] == 1
    assert gap["best_distance"] == 0.9
    assert gap["conversation_ids"] == [chat["conversation_id"]]


def test_close_context_is_not_a_gap(client, tenant):
    chat = _chat(client, tenant, "ok", message="Quanto costa la spedizione?")
    _log_turn(tenant["cid"], chat["conversation_id"], "escalated_model", distance=0.2)
    assert client.get("/analytics/knowledge-gaps", headers=tenant["op"]).json()["gaps"] == []


def test_provider_outage_and_keyword_escalations_are_not_gaps(client, tenant):
    """Un provider giù o un'escalation per parola chiave non dicono nulla sulla knowledge base."""
    chat = _chat(client, tenant, "rumore", message="vorrei un rimborso")
    _log_turn(tenant["cid"], chat["conversation_id"], "escalated_llm_down", distance=None)
    _log_turn(tenant["cid"], chat["conversation_id"], "escalated_keyword", distance=None)

    assert client.get("/analytics/knowledge-gaps", headers=tenant["op"]).json()["gaps"] == []


def test_thumbs_down_makes_an_answered_turn_a_gap(client, tenant):
    chat = _chat(client, tenant, "pollice", message="Come funziona il reso?")
    client.post("/chat/feedback", headers=tenant["key"], json={
        "conversation_id": chat["conversation_id"],
        "message_id": chat["message_id"],
        "value": "down",
        "conversation_token": chat["conversation_token"],
    })
    # nessun log sintetico: /chat ha già registrato il turno con il suo message_id
    gaps = client.get("/analytics/knowledge-gaps", headers=tenant["op"]).json()["gaps"]
    assert [g["question"] for g in gaps] == ["Come funziona il reso?"]
    assert gaps[0]["negative_feedback"] == 1


def test_same_question_is_grouped_and_ranked_by_frequency(client, tenant):
    rare = _chat(client, tenant, "rara", message="Avete un negozio a Roma?")
    _log_turn(tenant["cid"], rare["conversation_id"], "escalated_model", distance=0.8)
    for index in range(3):
        chat = _chat(client, tenant, f"freq-{index}", message="  Fate CONSEGNE in Svizzera?  ")
        _log_turn(tenant["cid"], chat["conversation_id"], "escalated_model", distance=0.85)

    gaps = client.get("/analytics/knowledge-gaps", headers=tenant["op"]).json()["gaps"]
    assert len(gaps) == 2
    assert gaps[0]["occurrences"] == 3  # la più frequente per prima
    assert len(gaps[0]["conversation_ids"]) == 3
    assert gaps[1]["question"] == "Avete un negozio a Roma?"


def test_normalisation_groups_variants():
    assert analytics.question_hash("Fate consegne?") == analytics.question_hash("  fate   CONSEGNE  ")
    assert analytics.question_hash("Fate consegne?") != analytics.question_hash("Fate resi?")


def test_local_semantic_clustering_groups_paraphrases(client, tenant):
    questions = [
        "Spedite anche fuori dall'Italia?",
        "È possibile ricevere un ordine in Svizzera?",
        "Accettate pagamenti rateali?",
    ]
    for index, question in enumerate(questions):
        chat = _chat(client, tenant, f"semantic-{index}", message=question)
        _log_turn(tenant["cid"], chat["conversation_id"], "escalated_model", distance=0.9)

    gaps = client.get("/analytics/knowledge-gaps", headers=tenant["op"]).json()["gaps"]
    assert len(gaps) == 2
    delivery = next(gap for gap in gaps if gap["cluster_size"] == 2)
    assert delivery["occurrences"] == 2
    assert set(delivery["questions"]) == set(questions[:2])

    client.post("/analytics/knowledge-gaps/review", headers=tenant["op"], json={
        "question": delivery["question"], "questions": delivery["questions"], "status": "ignored",
    })
    remaining = client.get("/analytics/knowledge-gaps", headers=tenant["op"]).json()["gaps"]
    assert [gap["question"] for gap in remaining] == ["Accettate pagamenti rateali?"]


def test_reviewed_gap_disappears_from_the_list(client, tenant):
    chat = _chat(client, tenant, "review", message="Fate consegne in Svizzera?")
    _log_turn(tenant["cid"], chat["conversation_id"], "escalated_model", distance=0.9)

    review = client.post("/analytics/knowledge-gaps/review", headers=tenant["op"], json={
        "question": "fate consegne in svizzera", "status": "taught",
    })
    assert review.status_code == 200
    assert client.get("/analytics/knowledge-gaps", headers=tenant["op"]).json()["gaps"] == []

    with_reviewed = client.get(
        "/analytics/knowledge-gaps", headers=tenant["op"], params={"include_reviewed": True}
    ).json()
    assert [g["reviewed"] for g in with_reviewed["gaps"]] == [True]


def test_review_is_idempotent_and_validated(client, tenant):
    client.post("/analytics/knowledge-gaps/review", headers=tenant["op"], json={"question": "X", "status": "taught"})
    client.post("/analytics/knowledge-gaps/review", headers=tenant["op"], json={"question": "x ", "status": "ignored"})
    with Session(db.engine) as session:
        rows = session.exec(select(db.KnowledgeGapReview)).all()
    assert len(rows) == 1
    assert rows[0].status == "ignored"

    assert client.post(
        "/analytics/knowledge-gaps/review", headers=tenant["op"], json={"question": "Y", "status": "boh"}
    ).status_code == 400


def test_gap_can_create_editable_local_article_draft(client, tenant):
    chat = _chat(client, tenant, "draft", message="Fate consegne in Svizzera?")
    _log_turn(tenant["cid"], chat["conversation_id"], "escalated_model", distance=0.9)

    created = client.post("/analytics/knowledge-gaps/draft", headers=tenant["op"], json={
        "question": "Fate consegne in Svizzera?", "questions": ["Fate consegne in Svizzera?"],
    })
    assert created.status_code == 200
    draft = created.json()
    assert draft["status"] == "draft"
    assert draft["baseline_occurrences"] == 1
    assert "[DA COMPLETARE" in draft["content"]
    assert client.get("/analytics/knowledge-drafts", headers=tenant["op"]).json()[0]["id"] == draft["id"]


def test_draft_requires_review_then_publishes_and_closes_cluster(client, tenant):
    chat = _chat(client, tenant, "publish-draft", message="Accettate pagamenti rateali?")
    _log_turn(tenant["cid"], chat["conversation_id"], "escalated_model", distance=0.9)
    draft = client.post("/analytics/knowledge-gaps/draft", headers=tenant["op"], json={
        "question": "Accettate pagamenti rateali?",
    }).json()

    incomplete = client.post(f"/analytics/knowledge-drafts/{draft['id']}/publish", headers=tenant["op"], json={
        "title": draft["title"], "content": draft["content"],
    })
    assert incomplete.status_code == 400
    published = client.post(f"/analytics/knowledge-drafts/{draft['id']}/publish", headers=tenant["op"], json={
        "title": "Pagamenti rateali", "content": "Il pagamento rateale è disponibile alle condizioni verificate.",
    })
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["job_status"] == "queued"
    assert published.json()["occurrences_after_publish"] == 0
    assert client.get("/analytics/knowledge-gaps", headers=tenant["op"]).json()["gaps"] == []


def test_knowledge_drafts_are_tenant_scoped(client, tenant):
    chat = _chat(client, tenant, "draft-scope", message="Quanto dura la garanzia?")
    _log_turn(tenant["cid"], chat["conversation_id"], "escalated_model", distance=0.9)
    draft = client.post("/analytics/knowledge-gaps/draft", headers=tenant["op"], json={
        "question": "Quanto dura la garanzia?",
    }).json()
    other = _other_tenant(client, "Draft Other")
    assert client.get("/analytics/knowledge-drafts", headers=other["op"]).json() == []
    assert client.post(f"/analytics/knowledge-drafts/{draft['id']}/publish", headers=other["op"], json={
        "title": "No", "content": "Non deve essere pubblicato.",
    }).status_code == 404
    assert client.post(
        "/analytics/knowledge-gaps/review", headers=tenant["op"], json={"question": "  ", "status": "taught"}
    ).status_code == 400


def test_gaps_group_open_themes_by_topic(client, tenant):
    chat = _chat(client, tenant, "tema", message="vorrei un rimborso")
    with Session(db.engine) as session:
        conv = session.get(db.Conversation, chat["conversation_id"])
        conv.ai_topic = "spedizioni estero"
        conv.ai_classified_at = datetime.utcnow()
        session.add(conv)
        session.commit()

    payload = client.get("/analytics/knowledge-gaps", headers=tenant["op"]).json()
    assert payload["by_topic"] == [{"topic": "spedizioni estero", "conversations": 1}]


# ---- isolation ----


def test_analytics_are_tenant_scoped(client, tenant):
    chat = _chat(client, tenant, "mio", message="Domanda senza risposta?")
    _log_turn(tenant["cid"], chat["conversation_id"], "escalated_model", distance=0.9)
    other = _other_tenant(client)

    assert client.get("/analytics/overview", headers=other["op"]).json()["conversations"] == 0
    assert client.get("/analytics/knowledge-gaps", headers=other["op"]).json()["gaps"] == []

    # una review dell'altro tenant non nasconde il gap del primo
    client.post("/analytics/knowledge-gaps/review", headers=other["op"], json={
        "question": "Domanda senza risposta?", "status": "ignored",
    })
    assert client.get("/analytics/knowledge-gaps", headers=tenant["op"]).json()["total"] == 1


def test_analytics_require_an_operator_session(client, tenant):
    assert client.get("/analytics/overview").status_code == 401
    assert client.get("/analytics/knowledge-gaps", headers=tenant["key"]).status_code == 401
