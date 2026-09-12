import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.middleware import ObservabilityMiddleware
from app.api.customer import router as customer_router
from app.api.agent import router as agent_router
from app.api.admin import router as admin_router

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Production-ready E-commerce Support Bot with LangGraph, pgvector, and Human Escalation"
)

# Cross-Origin Resource Sharing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom Audit & Latency Middleware
app.add_middleware(ObservabilityMiddleware)

# Routers
app.include_router(customer_router)
app.include_router(agent_router)
app.include_router(admin_router)

# Mount Static Files (Frontend UI)
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend"))
if not os.path.exists(static_dir):
    static_dir = "/app/static"

if os.path.exists(static_dir):
    app.mount("/ui", StaticFiles(directory=static_dir, html=True), name="static")


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "env": settings.APP_ENV,
        "app": settings.APP_NAME
    }
