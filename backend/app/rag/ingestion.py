import hashlib
import glob
import os
import uuid
import logging
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from app.models.schema import KnowledgeDocument, KnowledgeChunk
from app.core.config import settings

logger = logging.getLogger("ingestion")


class KnowledgeIngestionService:
    def __init__(self):
        try:
            self.embeddings = GoogleGenerativeAIEmbeddings(
                model=settings.EMBEDDING_MODEL,
                output_dimensionality=settings.EMBEDDING_DIMENSION,
                google_api_key=settings.GEMINI_API_KEY
            )
        except Exception:
            self.embeddings = None

    @staticmethod
    def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            chunks.append(chunk)
            start += chunk_size - overlap
        return chunks

    async def ingest_directory(self, session: AsyncSession, directory_path: str):
        files = glob.glob(os.path.join(directory_path, "*.md")) + glob.glob(os.path.join(directory_path, "*.txt"))
        for file_path in files:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            title = os.path.splitext(os.path.basename(file_path))[0].replace("_", " ").title()
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            # Check existing document
            stmt = select(KnowledgeDocument).where(KnowledgeDocument.source == file_path)
            res = await session.execute(stmt)
            existing_doc = res.scalar_one_or_none()

            if existing_doc and existing_doc.content_hash == content_hash:
                logger.info(f"Skipping {file_path}, already up-to-date.")
                continue

            if existing_doc:
                await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == existing_doc.id))
                doc = existing_doc
                doc.content_hash = content_hash
            else:
                doc = KnowledgeDocument(
                    title=title,
                    source=file_path,
                    content_hash=content_hash,
                    metadata_={"filename": os.path.basename(file_path)}
                )
                session.add(doc)
                await session.flush()

            raw_chunks = self.chunk_text(content)
            for idx, c_text in enumerate(raw_chunks):
                if self.embeddings and settings.GEMINI_API_KEY and settings.GEMINI_API_KEY != "test-api-key":
                    vector = await self.embeddings.aembed_query(c_text)
                else:
                    vector = [0.0] * 768

                chunk = KnowledgeChunk(
                    document_id=doc.id,
                    chunk_index=idx,
                    content=c_text,
                    embedding=vector,
                    metadata_={"index": idx}
                )
                session.add(chunk)

            await session.commit()
            logger.info(f"Ingested {file_path} with {len(raw_chunks)} chunks.")
