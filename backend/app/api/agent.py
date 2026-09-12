import uuid
import asyncio
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.database import get_db
from app.services.ticket_service import TicketService
from app.services.sse_manager import sse_manager
from app.services.conversation_service import ConversationService
from app.models.schema import ConversationStatus

router = APIRouter(prefix="/api/v1/agent", tags=["Agent Operations"])


class ClaimTicketRequest(BaseModel):
    agent_id: uuid.UUID


class AgentReplyRequest(BaseModel):
    agent_id: uuid.UUID
    message: str


@router.get("/tickets")
async def list_open_tickets(db: AsyncSession = Depends(get_db)):
    return await TicketService.get_active_queue(db)


@router.post("/tickets/{ticket_id}/claim")
async def claim_ticket(ticket_id: uuid.UUID, req: ClaimTicketRequest, db: AsyncSession = Depends(get_db)):
    ticket = await TicketService.claim(db, ticket_id, req.agent_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not available or already claimed.")
    
    await sse_manager.broadcast_to_conversation(
        str(ticket.conversation_id), 
        "AGENT_CLAIMED", 
        {"agent_id": str(req.agent_id)}
    )
    return {"status": "SUCCESS", "ticket_id": ticket.id, "state": ticket.status.value}


@router.post("/tickets/{ticket_id}/messages")
async def send_agent_reply(ticket_id: uuid.UUID, req: AgentReplyRequest, db: AsyncSession = Depends(get_db)):
    ticket = await TicketService.get(db, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    
    await ConversationService.append_message(
        db, ticket.conversation_id, sender_type="AGENT", content=req.message, sender_id=str(req.agent_id)
    )
    await sse_manager.broadcast_to_conversation(
        str(ticket.conversation_id),
        "NEW_MESSAGE",
        {"sender": "AGENT", "content": req.message}
    )
    return {"status": "SENT"}


@router.post("/tickets/{ticket_id}/return-to-bot")
async def return_to_bot(ticket_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    ticket = await TicketService.get(db, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found.")
        
    await TicketService.resolve(db, ticket_id)
    conv = await ConversationService.get(db, ticket.conversation_id)
    if conv:
        conv.status = ConversationStatus.ACTIVE
        await db.commit()
    
    await sse_manager.broadcast_to_conversation(
        str(ticket.conversation_id),
        "RETURNED_TO_BOT",
        {"message": "Conversation returned to automated assistant."}
    )
    return {"status": "RETURNED_TO_BOT"}


@router.get("/events")
async def agent_dashboard_stream():
    queue = await sse_manager.subscribe_agent_dashboard()

    async def event_generator():
        try:
            while True:
                data = await queue.get()
                yield {"data": data}
        except asyncio.CancelledError:
            sse_manager.unsubscribe_agent_dashboard(queue)

    return EventSourceResponse(event_generator())
