import uuid
from typing import List, Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.schema import SupportTicket, EscalationEvent, TicketStatus, TicketPriority, Customer, Conversation


class TicketService:
    @staticmethod
    async def create_ticket(
        session: AsyncSession,
        conversation_id: uuid.UUID,
        customer_id: uuid.UUID,
        priority: str,
        reason: str,
        summary: Optional[str] = None
    ) -> SupportTicket:
        p_enum = TicketPriority[priority.upper()] if (priority and priority.upper() in TicketPriority.__members__) else TicketPriority.MEDIUM
        
        # Ensure reason is never None or whitespace
        safe_reason = reason.strip() if (reason and isinstance(reason, str) and reason.strip()) else "Customer Escalation Request"
        
        ticket = SupportTicket(
            conversation_id=conversation_id,
            customer_id=customer_id,
            priority=p_enum,
            reason=safe_reason,
            status=TicketStatus.OPEN,
            summary=summary
        )
        session.add(ticket)
        await session.flush()

        # Record escalation event
        event = EscalationEvent(
            ticket_id=ticket.id,
            conversation_id=conversation_id,
            reason=safe_reason,
            confidence=0.5,
            metadata_={"summary": summary}
        )
        session.add(event)
        await session.flush()
        return ticket

    @staticmethod
    async def get_active_queue(session: AsyncSession) -> List[Dict[str, Any]]:
        stmt = (
            select(SupportTicket, Customer.name, Customer.email)
            .join(Customer, SupportTicket.customer_id == Customer.id)
            .where(SupportTicket.status.in_([TicketStatus.OPEN, TicketStatus.WAITING_FOR_AGENT, TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS]))
            .order_by(SupportTicket.created_at.desc())
        )
        result = await session.execute(stmt)
        rows = result.all()
        return [
            {
                "id": str(t.id),
                "conversation_id": str(t.conversation_id),
                "customer_id": str(t.customer_id),
                "customer_name": name,
                "customer_email": email,
                "priority": t.priority.value,
                "reason": t.reason,
                "status": t.status.value,
                "assigned_agent_id": str(t.assigned_agent_id) if t.assigned_agent_id else None,
                "summary": t.summary,
                "created_at": t.created_at.isoformat()
            }
            for t, name, email in rows
        ]

    @staticmethod
    async def claim(session: AsyncSession, ticket_id: uuid.UUID, agent_id: uuid.UUID) -> Optional[SupportTicket]:
        stmt = select(SupportTicket).where(SupportTicket.id == ticket_id).with_for_update()
        res = await session.execute(stmt)
        ticket = res.scalar_one_or_none()
        if not ticket:
            return None
        ticket.assigned_agent_id = agent_id
        ticket.status = TicketStatus.IN_PROGRESS
        await session.commit()
        return ticket

    @staticmethod
    async def get(session: AsyncSession, ticket_id: uuid.UUID) -> Optional[SupportTicket]:
        stmt = select(SupportTicket).where(SupportTicket.id == ticket_id)
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def resolve(session: AsyncSession, ticket_id: uuid.UUID) -> Optional[SupportTicket]:
        stmt = select(SupportTicket).where(SupportTicket.id == ticket_id)
        res = await session.execute(stmt)
        ticket = res.scalar_one_or_none()
        if ticket:
            ticket.status = TicketStatus.RESOLVED
            await session.commit()
        return ticket
