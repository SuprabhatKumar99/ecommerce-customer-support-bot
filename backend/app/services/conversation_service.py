import uuid
from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.schema import Conversation, Message, ConversationStatus


class ConversationService:
    @staticmethod
    async def create(session: AsyncSession, customer_id: uuid.UUID) -> Conversation:
        conv = Conversation(customer_id=customer_id, status=ConversationStatus.ACTIVE)
        session.add(conv)
        await session.commit()
        await session.refresh(conv)
        return conv

    @staticmethod
    async def get(session: AsyncSession, conversation_id: uuid.UUID) -> Optional[Conversation]:
        stmt = select(Conversation).where(Conversation.id == conversation_id)
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def append_message(
        session: AsyncSession,
        conversation_id: uuid.UUID,
        sender_type: str,
        content: str,
        sender_id: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            sender_type=sender_type,
            sender_id=sender_id,
            content=content,
            metadata_=metadata or {}
        )
        session.add(msg)
        await session.commit()
        return msg

    @staticmethod
    async def get_messages(session: AsyncSession, conversation_id: uuid.UUID) -> List[Message]:
        stmt = select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.asc())
        res = await session.execute(stmt)
        return res.scalars().all()
