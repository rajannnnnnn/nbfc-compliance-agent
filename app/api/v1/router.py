from fastapi import APIRouter

from app.api.v1 import assessments, corpus, documents, health, loans

router = APIRouter()
router.include_router(health.router)
router.include_router(corpus.router)
router.include_router(loans.router)
router.include_router(documents.router)
router.include_router(assessments.router)
