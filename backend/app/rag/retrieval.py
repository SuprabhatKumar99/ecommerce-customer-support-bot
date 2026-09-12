import uuid
import logging
from typing import List, Dict, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from app.core.config import settings

logger = logging.getLogger("rag")


class RAGRetriever:
    def __init__(self):
        try:
            self.embeddings = GoogleGenerativeAIEmbeddings(
                model=settings.EMBEDDING_MODEL,
                output_dimensionality=settings.EMBEDDING_DIMENSION,
                google_api_key=settings.GEMINI_API_KEY
            )
        except Exception as e:
            logger.warning(f"Could not initialize remote GoogleGenerativeAIEmbeddings: {e}")
            self.embeddings = None

    async def retrieve(
        self, 
        session: AsyncSession, 
        query: str, 
        top_k: int = 4, 
        similarity_threshold: float = 0.50
    ) -> List[Dict[str, Any]]:
        if not self.embeddings or not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY == "test-api-key":
            logger.info("Using mock vector retrieval for development or unconfigured API key.")
            # Fallback simple text match for local testing
            query_sql = text("""
                SELECT 
                    c.id AS chunk_id,
                    d.title AS document_title,
                    d.source AS document_source,
                    c.content,
                    0.85 AS similarity
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON c.document_id = d.id
                LIMIT :top_k;
            """)
            result = await session.execute(query_sql, {"top_k": top_k})
            rows = result.fetchall()
            return [
                {
                    "chunk_id": str(r.chunk_id),
                    "title": r.document_title,
                    "source": r.document_source,
                    "content": r.content,
                    "similarity": float(r.similarity)
                }
                for r in rows
            ]

        try:
            query_vector = await self.embeddings.aembed_query(query)
            vector_str = f"[{','.join(map(str, query_vector))}]"
            
            query_sql = text("""
                SELECT 
                    c.id AS chunk_id,
                    d.title AS document_title,
                    d.source AS document_source,
                    c.content,
                    1 - (c.embedding <=> :vector::vector) AS similarity
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON c.document_id = d.id
                WHERE 1 - (c.embedding <=> :vector::vector) >= :threshold
                ORDER BY similarity DESC
                LIMIT :top_k;
            """)
            
            result = await session.execute(
                query_sql, 
                {"vector": vector_str, "threshold": similarity_threshold, "top_k": top_k}
            )
            rows = result.fetchall()
            return [
                {
                    "chunk_id": str(row.chunk_id),
                    "title": row.document_title,
                    "source": row.document_source,
                    "content": row.content,
                    "similarity": float(row.similarity)
                }
                for row in rows
            ]
        except Exception as ex:
            logger.error(f"Vector search failed: {ex}")
            return []
