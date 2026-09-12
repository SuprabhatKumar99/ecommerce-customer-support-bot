from typing import Annotated, Literal, Optional, List, Dict, Any
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from langgraph.graph.message import add_messages


class SupportState(TypedDict):
    conversation_id: str
    customer_id: str
    messages: Annotated[list, add_messages]
    
    intent: Optional[str]
    intent_confidence: float
    order_id: Optional[str]
    
    retrieved_documents: list[dict]
    tool_results: list[dict]
    consecutive_failures: int
    
    escalation_required: bool
    escalation_reason: Optional[str]
    escalation_priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    ticket_id: Optional[str]
    
    response: Optional[str]


class IntentResult(BaseModel):
    intent: Literal[
        "FAQ",
        "PRODUCT",
        "ORDER_STATUS",
        "CANCEL_ORDER",
        "RETURN",
        "REFUND",
        "DELIVERY_ISSUE",
        "COMPLAINT",
        "HUMAN_HANDOFF",
        "OTHER",
    ]
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score between 0 and 1")
    order_id: Optional[str] = Field(default=None, description="UUID of order if present in context")
    frustration_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Frustration metric")
    requires_human: bool = Field(default=False, description="Flag indicating human escalation needed")
    reason: Optional[str] = Field(default=None, description="Reason for classification")
