"""L'assistente dentro il pannello: emissione del token di contesto.

Un solo endpoint, e tutto il ragionamento sta in `app/panel_assistant.py`. Qui c'è la parte che
non si può delegare: **chi chiede** deve essere un operatore con una sessione valida, e il tenant
per cui si emette il token è quello del suo account — mai un `client_id` scelto dal chiamante.
Nessun parametro in ingresso, quindi, ed è il punto: un endpoint che accetta il tenant di cui
parlare è un endpoint che lo concede.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

from .. import panel_assistant
from ..db import Operator
from ..deps import require_operator
from ..logging_config import log

logger = logging.getLogger("wpai")

router = APIRouter()


@router.post("/panel/assistant/token")
def panel_assistant_token(operator: Operator = Depends(require_operator)) -> dict:
    """Un token di contesto di 5 minuti per l'operatore loggato.

    `503` quando il segreto di firma non è configurato, invece di un token che nessuno potrà
    verificare: la funzione è spenta, e deve dirlo. Il pannello lo legge come «assistente non
    disponibile» e non mostra il launcher.
    """
    if not panel_assistant.configured():
        raise HTTPException(503, "assistente del pannello non configurato")
    token = panel_assistant.issue_token(operator.client_id, operator.id)
    log(
        logger,
        logging.INFO,
        "panel_assistant.token_issued",
        client_id=operator.client_id,
        operator_id=operator.id,
    )
    return {"token": token, "expires_in": panel_assistant.TOKEN_TTL_SECONDS}
