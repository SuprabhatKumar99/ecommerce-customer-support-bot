import asyncio
import json
from typing import Dict, Set


class SSEConnectionManager:
    def __init__(self):
        self._conversations: Dict[str, Set[asyncio.Queue]] = {}
        self._agent_dashboards: Set[asyncio.Queue] = set()

    async def subscribe_conversation(self, conversation_id: str) -> asyncio.Queue:
        queue = asyncio.Queue()
        if conversation_id not in self._conversations:
            self._conversations[conversation_id] = set()
        self._conversations[conversation_id].add(queue)
        return queue

    def unsubscribe_conversation(self, conversation_id: str, queue: asyncio.Queue):
        if conversation_id in self._conversations:
            self._conversations[conversation_id].discard(queue)
            if not self._conversations[conversation_id]:
                del self._conversations[conversation_id]

    async def subscribe_agent_dashboard(self) -> asyncio.Queue:
        queue = asyncio.Queue()
        self._agent_dashboards.add(queue)
        return queue

    def unsubscribe_agent_dashboard(self, queue: asyncio.Queue):
        self._agent_dashboards.discard(queue)

    async def broadcast_to_conversation(self, conversation_id: str, event_type: str, data: dict):
        payload = json.dumps({"event": event_type, "data": data})
        if conversation_id in self._conversations:
            for queue in list(self._conversations[conversation_id]):
                await queue.put(payload)

    async def broadcast_ticket_update(self, event_type: str, ticket_data: dict):
        payload = json.dumps({"event": event_type, "data": ticket_data})
        for queue in list(self._agent_dashboards):
            await queue.put(payload)


sse_manager = SSEConnectionManager()
