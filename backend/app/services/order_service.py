import uuid
from typing import Dict, Any, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.schema import Order, Return, Refund, OrderStatus, ReturnStatus, RefundStatus


class OrderService:
    @staticmethod
    async def get_customer_order(session: AsyncSession, order_id: uuid.UUID, customer_id: uuid.UUID) -> Dict[str, Any]:
        stmt = select(Order).where(Order.id == order_id, Order.customer_id == customer_id)
        result = await session.execute(stmt)
        order = result.scalar_one_or_none()
        if not order:
            return {"error": "Order not found or does not belong to this customer."}
        
        return {
            "order_id": str(order.id),
            "status": order.status.value,
            "total_amount": str(order.total_amount),
            "tracking_number": order.tracking_number,
            "carrier": order.carrier,
            "estimated_delivery": order.estimated_delivery.isoformat() if order.estimated_delivery else None,
            "created_at": order.created_at.isoformat()
        }

    @staticmethod
    async def get_customer_orders(session: AsyncSession, customer_id: uuid.UUID, limit: int = 5) -> List[Dict[str, Any]]:
        stmt = select(Order).where(Order.customer_id == customer_id).order_by(Order.created_at.desc()).limit(limit)
        result = await session.execute(stmt)
        orders = result.scalars().all()
        return [
            {
                "order_id": str(o.id),
                "status": o.status.value,
                "total_amount": str(o.total_amount),
                "created_at": o.created_at.isoformat()
            }
            for o in orders
        ]

    @staticmethod
    async def cancel_order(session: AsyncSession, order_id: uuid.UUID, customer_id: uuid.UUID) -> Dict[str, Any]:
        stmt = select(Order).where(Order.id == order_id, Order.customer_id == customer_id).with_for_update()
        result = await session.execute(stmt)
        order = result.scalar_one_or_none()
        
        if not order:
            return {"success": False, "error": "Order not found or does not belong to this customer."}
        
        if order.status not in (OrderStatus.PENDING, OrderStatus.PROCESSING):
            return {
                "success": False, 
                "error": f"Cannot cancel order with status '{order.status.value}'. Cancellations are only permitted prior to shipping."
            }
        
        order.status = OrderStatus.CANCELLED
        await session.flush()
        
        return {
            "success": True, 
            "order_id": str(order.id), 
            "new_status": OrderStatus.CANCELLED.value,
            "message": "Order was successfully cancelled."
        }

    @staticmethod
    async def create_return_request(session: AsyncSession, order_id: uuid.UUID, customer_id: uuid.UUID, reason: str) -> Dict[str, Any]:
        stmt = select(Order).where(Order.id == order_id, Order.customer_id == customer_id).with_for_update()
        result = await session.execute(stmt)
        order = result.scalar_one_or_none()
        
        if not order:
            return {"success": False, "error": "Order not found or ownership mismatch."}
            
        if order.status != OrderStatus.DELIVERED:
            return {
                "success": False, 
                "error": f"Return invalid: Order is currently '{order.status.value}'. Items must be DELIVERED to request a return."
            }

        ret_stmt = select(Return).where(Return.order_id == order_id)
        existing_ret = (await session.execute(ret_stmt)).scalar_one_or_none()
        if existing_ret:
            return {"success": False, "error": f"Return already exists in status '{existing_ret.status.value}'."}

        new_return = Return(
            order_id=order.id,
            customer_id=customer_id,
            status=ReturnStatus.REQUESTED,
            reason=reason
        )
        session.add(new_return)
        order.status = OrderStatus.RETURN_REQUESTED
        await session.flush()
        
        return {
            "success": True,
            "return_id": str(new_return.id),
            "order_id": str(order.id),
            "status": ReturnStatus.REQUESTED.value,
            "message": "Return request submitted successfully."
        }

    @staticmethod
    async def get_refund_status(session: AsyncSession, order_id: uuid.UUID, customer_id: uuid.UUID) -> Dict[str, Any]:
        stmt = select(Refund).join(Order, Refund.order_id == Order.id).where(
            Refund.order_id == order_id, Order.customer_id == customer_id
        )
        result = await session.execute(stmt)
        refund = result.scalar_one_or_none()
        if not refund:
            return {"refund_found": False, "message": "No refund record located for this order."}
        return {
            "refund_found": True,
            "refund_id": str(refund.id),
            "amount": str(refund.amount),
            "status": refund.status.value,
            "transaction_reference": refund.transaction_reference,
            "created_at": refund.created_at.isoformat()
        }
