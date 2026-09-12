import uuid
import re
from typing import Literal
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from app.graph.state import SupportState, IntentResult
from app.rag.retrieval import RAGRetriever
from app.services.order_service import OrderService
from app.services.ticket_service import TicketService
from app.core.config import settings
from app.core.database import AsyncSessionLocal


def get_llm():
    if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY == "test-api-key":
        return None
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        temperature=0.0,
        google_api_key=settings.GEMINI_API_KEY
    )


rag_retriever = RAGRetriever()

def extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item.get("text", "")))
            elif hasattr(item, "text"):
                parts.append(str(item.text))
        return "".join(parts).strip() or str(content)
    return str(content)



async def load_context(state: SupportState) -> dict:
    return {
        "retrieved_documents": [],
        "tool_results": [],
        "escalation_required": False,
        "escalation_reason": None,
        "consecutive_failures": state.get("consecutive_failures", 0)
    }


async def classify_intent(state: SupportState) -> dict:
    latest_msg = extract_text(state["messages"][-1].content)
    llm = get_llm()
    
    # Fallback heuristic if API key is not configured
    if not llm:
        lower = latest_msg.lower()
        extracted_order_id = None
        uuid_match = re.search(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', latest_msg)
        if uuid_match:
            extracted_order_id = uuid_match.group(0)

        if any(w in lower for w in ["human", "agent", "person", "representative"]):
            return {"intent": "HUMAN_HANDOFF", "intent_confidence": 1.0, "escalation_required": True, "escalation_priority": "HIGH", "order_id": extracted_order_id}
        if "cancel" in lower:
            return {"intent": "CANCEL_ORDER", "intent_confidence": 0.95, "order_id": extracted_order_id, "escalation_required": False, "escalation_priority": "MEDIUM"}
        if "return" in lower:
            return {"intent": "RETURN", "intent_confidence": 0.95, "order_id": extracted_order_id, "escalation_required": False, "escalation_priority": "MEDIUM"}
        if "refund" in lower:
            return {"intent": "REFUND", "intent_confidence": 0.90, "order_id": extracted_order_id, "escalation_required": False, "escalation_priority": "MEDIUM"}
        if any(w in lower for w in ["order", "track", "where"]):
            return {"intent": "ORDER_STATUS", "intent_confidence": 0.95, "order_id": extracted_order_id, "escalation_required": False, "escalation_priority": "MEDIUM"}
        if "complaint" in lower or "terrible" in lower or "angry" in lower:
            return {"intent": "COMPLAINT", "intent_confidence": 0.95, "escalation_required": True, "escalation_priority": "HIGH", "order_id": extracted_order_id}
        return {"intent": "FAQ", "intent_confidence": 0.90, "escalation_required": False, "escalation_priority": "LOW", "order_id": extracted_order_id}

    structured_classifier = llm.with_structured_output(IntentResult)
    system_prompt = (
        "You are an intent classification system for an e-commerce platform. "
        "Analyze the conversation and extract the intent, confidence score (0.0 to 1.0), "
        "frustration score (0.0 to 1.0), and any referenced Order UUID."
    )
    result: IntentResult = await structured_classifier.ainvoke([
        SystemMessage(content=system_prompt),
        *state["messages"][-5:]
    ])
    
    requires_esc = result.requires_human or result.frustration_score >= 0.80
    return {
        "intent": result.intent,
        "intent_confidence": result.confidence,
        "order_id": result.order_id or state.get("order_id"),
        "escalation_required": requires_esc,
        "escalation_reason": "High frustration or sensitive request" if requires_esc else None,
        "escalation_priority": "HIGH" if result.frustration_score >= 0.80 else "MEDIUM"
    }


async def execute_rag(state: SupportState) -> dict:
    query = extract_text(state["messages"][-1].content)
    async with AsyncSessionLocal() as session:
        chunks = await rag_retriever.retrieve(session, query=query, top_k=4)
    return {"retrieved_documents": chunks}


async def execute_ecommerce_tool(state: SupportState) -> dict:
    intent = state["intent"]
    order_id_str = state.get("order_id")
    customer_id = uuid.UUID(state["customer_id"])
    
    if not order_id_str:
        return {
            "tool_results": [{"error": "Missing Order ID"}],
            "response": "Could you please provide your Order ID (UUID format) so I can assist you with that?"
        }
    
    try:
        order_uuid = uuid.UUID(order_id_str)
    except ValueError:
        return {
            "tool_results": [{"error": "Invalid Order ID format"}],
            "response": "The Order ID provided is invalid. Please double-check the ID from your receipt."
        }

    async with AsyncSessionLocal() as session:
        tool_res = {}
        if intent in ("ORDER_STATUS", "DELIVERY_ISSUE"):
            tool_res = await OrderService.get_customer_order(session, order_uuid, customer_id)
        elif intent == "CANCEL_ORDER":
            tool_res = await OrderService.cancel_order(session, order_uuid, customer_id)
        elif intent == "RETURN":
            tool_res = await OrderService.create_return_request(
                session, order_uuid, customer_id, reason=extract_text(state["messages"][-1].content)
            )
        elif intent == "REFUND":
            tool_res = await OrderService.get_refund_status(session, order_uuid, customer_id)
        await session.commit()
    
    is_failure = "error" in tool_res or tool_res.get("success") is False
    current_failures = state.get("consecutive_failures", 0) + (1 if is_failure else 0)
    
    return {
        "tool_results": [tool_res],
        "consecutive_failures": current_failures if is_failure else 0
    }


async def evaluate_escalation(state: SupportState) -> dict:
    intent = state.get("intent")
    confidence = state.get("intent_confidence", 1.0)
    failures = state.get("consecutive_failures", 0)
    
    if state.get("escalation_required"):
        return {"escalation_required": True}
        
    if intent in ("COMPLAINT", "HUMAN_HANDOFF"):
        return {
            "escalation_required": True, 
            "escalation_reason": "Explicit escalation or formal complaint", 
            "escalation_priority": "HIGH"
        }
        
    if failures >= 2:
        return {
            "escalation_required": True, 
            "escalation_reason": "Repeated tool or operational failure", 
            "escalation_priority": "HIGH"
        }
        
    if confidence < 0.50:
        return {
            "escalation_required": True, 
            "escalation_reason": f"Low confidence classification ({confidence:.2f})", 
            "escalation_priority": "MEDIUM"
        }
        
    return {"escalation_required": False}


async def generate_response(state: SupportState) -> dict:
    if state.get("response"):
        return {"messages": [AIMessage(content=state["response"])]}

    llm = get_llm()
    docs = state.get("retrieved_documents", [])
    tool_results = state.get("tool_results", [])
    
    if not llm:
        if tool_results:
            first_res = tool_results[0]
            if "error" in first_res:
                ans = f"Notice: {first_res['error']}"
            elif first_res.get("status") == "CANCELLED":
                ans = f"Your order {first_res.get('order_id')} has been successfully cancelled."
            elif first_res.get("status") == "REQUESTED":
                ans = f"Your return request for order {first_res.get('order_id')} has been submitted."
            elif "status" in first_res:
                ans = f"Order {first_res.get('order_id')} is currently {first_res.get('status')}. Carrier: {first_res.get('carrier')}, Tracking: {first_res.get('tracking_number')}."
            else:
                ans = str(first_res)
        elif docs:
            ans = f"Based on our policy: {docs[0]['content']}"
        else:
            ans = "How can I help you with your order, shipping, returns, or product questions today?"
        return {"messages": [AIMessage(content=ans)], "response": ans}

    context_str = ""
    if docs:
        context_str += "Knowledge Base Sources:\n"
        for doc in docs:
            context_str += f"- [{doc['title']}]: {doc['content']}\n"
    if tool_results:
        context_str += f"\nVerified System Operation Results:\n{tool_results}\n"
        
    system_prompt = (
        "You are an e-commerce customer support assistant. "
        "Formulate a helpful, concise, and professional answer based strictly on the provided Context. "
        "Never invent tracking details or policy rules not present in Context. "
        "Always cite source titles when answering policy questions."
    )
    prompt = f"{system_prompt}\n\nContext:\n{context_str}"
    ai_msg = await llm.ainvoke([SystemMessage(content=prompt), *state["messages"][-4:]])
    raw_content = ai_msg.content
    if isinstance(raw_content, list):
        parts = []
        for p in raw_content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and p.get("type") == "text":
                parts.append(p.get("text", ""))
            elif isinstance(p, dict) and "text" in p:
                parts.append(str(p.get("text", "")))
            elif hasattr(p, "text"):
                parts.append(str(p.text))
        text_response = "".join(parts).strip() or str(raw_content)
    else:
        text_response = str(raw_content)

    return {"messages": [ai_msg], "response": text_response}


async def escalate_and_create_ticket(state: SupportState) -> dict:
    async with AsyncSessionLocal() as session:
        ticket = await TicketService.create_ticket(
            session=session,
            conversation_id=uuid.UUID(state["conversation_id"]),
            customer_id=uuid.UUID(state["customer_id"]),
            priority=state.get("escalation_priority", "MEDIUM"),
            reason=state.get("escalation_reason", "AI Escalation Policy Triggered"),
            summary=f"Automated handoff. Intent: {state.get('intent')}. Last query: {extract_text(state['messages'][-1].content)}"
        )
        await session.commit()
    
    handoff_text = (
        "I've connected our customer support team and created a ticket for you. "
        f"A human agent has been assigned (Ticket ID: {ticket.id}) and will assist you shortly."
    )
    return {
        "ticket_id": str(ticket.id),
        "escalation_required": True,
        "response": handoff_text,
        "messages": [AIMessage(content=handoff_text)]
    }


def route_after_classification(state: SupportState) -> Literal["execute_rag", "execute_ecommerce_tool", "evaluate_escalation"]:
    if state.get("escalation_required"):
        return "evaluate_escalation"
    intent = state.get("intent")
    if intent in ("FAQ", "PRODUCT"):
        return "execute_rag"
    elif intent in ("ORDER_STATUS", "CANCEL_ORDER", "RETURN", "REFUND", "DELIVERY_ISSUE"):
        return "execute_ecommerce_tool"
    return "evaluate_escalation"


def route_after_evaluation(state: SupportState) -> Literal["escalate_and_create_ticket", "generate_response"]:
    return "escalate_and_create_ticket" if state.get("escalation_required") else "generate_response"


def create_support_graph():
    workflow = StateGraph(SupportState)
    
    workflow.add_node("load_context", load_context)
    workflow.add_node("classify_intent", classify_intent)
    workflow.add_node("execute_rag", execute_rag)
    workflow.add_node("execute_ecommerce_tool", execute_ecommerce_tool)
    workflow.add_node("evaluate_escalation", evaluate_escalation)
    workflow.add_node("generate_response", generate_response)
    workflow.add_node("escalate_and_create_ticket", escalate_and_create_ticket)
    
    workflow.set_entry_point("load_context")
    workflow.add_edge("load_context", "classify_intent")
    
    workflow.add_conditional_edges(
        "classify_intent",
        route_after_classification,
        {
            "execute_rag": "execute_rag",
            "execute_ecommerce_tool": "execute_ecommerce_tool",
            "evaluate_escalation": "evaluate_escalation"
        }
    )
    
    workflow.add_edge("execute_rag", "evaluate_escalation")
    workflow.add_edge("execute_ecommerce_tool", "evaluate_escalation")
    
    workflow.add_conditional_edges(
        "evaluate_escalation",
        route_after_evaluation,
        {
            "escalate_and_create_ticket": "escalate_and_create_ticket",
            "generate_response": "generate_response"
        }
    )
    
    workflow.add_edge("generate_response", END)
    workflow.add_edge("escalate_and_create_ticket", END)
    
    return workflow.compile()


support_graph = create_support_graph()
