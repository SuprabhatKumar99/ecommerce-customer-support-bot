import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
import asyncio

from app.core.database import get_db
from app.services.sse_manager import sse_manager
from app.graph.workflow import support_graph
from app.services.conversation_service import ConversationService
from app.models.schema import ConversationStatus

router = APIRouter(prefix="/api/v1/conversations", tags=["Customer Conversations"])


class CreateConversationRequest(BaseModel):
    customer_id: uuid.UUID


class MessageRequest(BaseModel):
    message: str


class MessageResponse(BaseModel):
    conversation_id: uuid.UUID
    response: str
    escalated: bool
    ticket_id: uuid.UUID | None = None


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_conversation(req: CreateConversationRequest, db: AsyncSession = Depends(get_db)):
    conv = await ConversationService.create(db, req.customer_id)
    return {"conversation_id": conv.id, "status": conv.status.value}


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    conv = await ConversationService.get(db, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    messages = await ConversationService.get_messages(db, conversation_id)
    return {
        "id": conv.id,
        "customer_id": conv.customer_id,
        "status": conv.status.value,
        "messages": [
            {
                "id": m.id,
                "sender_type": m.sender_type,
                "content": m.content,
                "created_at": m.created_at.isoformat()
            }
            for m in messages
        ]
    }


@router.post("/{conversation_id}/messages", response_model=MessageResponse)
async def send_message(
    conversation_id: uuid.UUID,
    req: MessageRequest,
    db: AsyncSession = Depends(get_db)
):
    conv = await ConversationService.get(db, conversation_id)
    if not conv or conv.status.value in ("CLOSED", "RESOLVED"):
        raise HTTPException(status_code=400, detail="Conversation is inactive or closed.")

    # If already escalated to an agent, AI graph is bypassed
    if conv.status.value == "ESCALATED":
        await ConversationService.append_message(
            db, conversation_id, sender_type="CUSTOMER", content=req.message
        )
        await sse_manager.broadcast_to_conversation(
            str(conversation_id), "NEW_MESSAGE", {"sender": "CUSTOMER", "content": req.message}
        )
        return MessageResponse(
            conversation_id=conversation_id,
            response="Your message has been forwarded directly to your assigned support agent.",
            escalated=True
        )

    inputs = {
        "conversation_id": str(conversation_id),
        "customer_id": str(conv.customer_id),
        "messages": [("user", req.message)]
    }
    
    final_state = await support_graph.ainvoke(inputs)
    
    await ConversationService.append_message(db, conversation_id, "CUSTOMER", req.message)
    raw_reply = final_state.get("response", "Thank you for reaching out.")
    if isinstance(raw_reply, list):
        parts = [p.get("text", "") if isinstance(p, dict) and p.get("type") == "text" else (p if isinstance(p, str) else "") for p in raw_reply]
        bot_reply = "".join(parts).strip() or str(raw_reply)
    else:
        bot_reply = str(raw_reply)
    await ConversationService.append_message(db, conversation_id, "BOT", bot_reply)
    
    ticket_id = final_state.get("ticket_id")
    if final_state.get("escalation_required") and ticket_id:
        conv.status = ConversationStatus.ESCALATED
        await db.commit()
        await sse_manager.broadcast_to_conversation(
            str(conversation_id), "AGENT_CONNECTED", {"ticket_id": ticket_id}
        )
        await sse_manager.broadcast_ticket_update(
            "TICKET_CREATED", {"ticket_id": ticket_id, "conversation_id": str(conversation_id)}
        )

    return MessageResponse(
        conversation_id=conversation_id,
        response=bot_reply,
        escalated=final_state.get("escalation_required", False),
        ticket_id=uuid.UUID(ticket_id) if ticket_id else None
    )


@router.post("/{conversation_id}/escalate")
async def force_escalate(conversation_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    conv = await ConversationService.get(db, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    
    inputs = {
        "conversation_id": str(conversation_id),
        "customer_id": str(conv.customer_id),
        "messages": [("user", "I demand to speak to a human representative immediately.")],
        "escalation_required": True,
        "escalation_reason": "Customer manual escalation request",
        "escalation_priority": "HIGH"
    }
    final_state = await support_graph.ainvoke(inputs)
    conv.status = ConversationStatus.ESCALATED
    await db.commit()
    
    ticket_id = final_state.get("ticket_id")
    await sse_manager.broadcast_to_conversation(
        str(conversation_id), "AGENT_CONNECTED", {"ticket_id": ticket_id}
    )
    return {"status": "ESCALATED", "ticket_id": ticket_id}


@router.get("/{conversation_id}/events")
async def conversation_sse_stream(conversation_id: uuid.UUID):
    queue = await sse_manager.subscribe_conversation(str(conversation_id))

    async def event_generator():
        try:
            while True:
                data = await queue.get()
                yield {"data": data}
        except asyncio.CancelledError:
            sse_manager.unsubscribe_conversation(str(conversation_id), queue)

    return EventSourceResponse(event_generator())
