import os
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.rag.ingestion import KnowledgeIngestionService

router = APIRouter(prefix="/api/v1/admin", tags=["Admin & Management"])


@router.post("/ingest-knowledge")
async def trigger_ingestion(db: AsyncSession = Depends(get_db)):
    service = KnowledgeIngestionService()
    knowledge_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../knowledge"))
    if not os.path.exists(knowledge_dir):
        knowledge_dir = "/knowledge"
    
    if os.path.exists(knowledge_dir):
        await service.ingest_directory(db, knowledge_dir)
        return {"status": "SUCCESS", "message": f"Ingested knowledge files from {knowledge_dir}"}
    return {"status": "ERROR", "message": "Knowledge directory not found."}
