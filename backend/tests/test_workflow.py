import pytest
from app.graph.workflow import route_after_classification, route_after_evaluation


def test_routing_rules():
    state_faq = {"intent": "FAQ", "escalation_required": False}
    assert route_after_classification(state_faq) == "execute_rag"

    state_order = {"intent": "ORDER_STATUS", "escalation_required": False}
    assert route_after_classification(state_order) == "execute_ecommerce_tool"

    state_complaint = {"intent": "COMPLAINT", "escalation_required": True}
    assert route_after_classification(state_complaint) == "evaluate_escalation"

    state_escalate = {"escalation_required": True}
    assert route_after_evaluation(state_escalate) == "escalate_and_create_ticket"

    state_continue = {"escalation_required": False}
    assert route_after_evaluation(state_continue) == "generate_response"
