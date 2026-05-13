"""
Main FastAPI Application
Scalable automation platform with job queue, real-time updates, and multi-tool support
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import time
import logging

from .core.config import settings
from .db.database import init_db, close_db
from .api import auth, system, websocket, funda, properties, emails

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan events.
    Startup: Initialize database
    Shutdown: Clean up connections
    """
    # Startup
    logger.info("Starting Automation Platform API...")
    logger.info(f"Version: {settings.APP_VERSION}")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"Debug Mode: {settings.DEBUG}")
    
    # Show environment URLs
    if settings.DOMAIN_NAME:
        logger.info(f"Domain: {settings.DOMAIN_NAME}")
        logger.info(f"Backend URL: {settings.backend_url}")
        logger.info(f"Frontend URL: {settings.frontend_url}")
    else:
        logger.info(f"Running on: http://{settings.HOST}:{settings.PORT}")
    
    # Initialize database
    try:
        await init_db()
        logger.info("✓ Database initialized")
    except Exception as e:
        logger.error(f"✗ Database initialization failed: {e}")
        raise
    
    # Check Redis connection
    try:
        from redis import Redis
        redis_client = Redis.from_url(settings.REDIS_URL)
        redis_client.ping()
        logger.info("✓ Redis connection established")
    except Exception as e:
        logger.warning(f"⚠ Redis connection failed: {e}")
    
    # Check Celery workers
    try:
        from .core.celery_app import celery_app
        inspect = celery_app.control.inspect()
        stats = inspect.stats()
        if stats:
            logger.info(f"✓ Celery workers active: {len(stats)}")
        else:
            logger.warning("⚠ No Celery workers found")
    except Exception as e:
        logger.warning(f"⚠ Celery check failed: {e}")
    
    logger.info(f"🚀 API Server ready")
    logger.info(f"📚 API Docs: {settings.backend_url}/docs")
    if settings.DOMAIN_NAME:
        logger.info(f"🌐 Access at: {settings.backend_url}")
    else:
        logger.info(f"🌐 Local access: http://{settings.HOST}:{settings.PORT}")

    # ── Funda: auto-resume an interrupted scrape ──────────────────
    # If the backend died mid-run (OOM, crash, ungraceful kill), the
    # run_state.json on disk still has in_progress=True. Resume that run
    # from the page it stopped on, reusing the original KVK snapshot so
    # the crashed run's own already-scraped properties aren't mis-counted
    # as duplicates. A graceful Stop / deliberate restart clears the flag,
    # so this only fires on a genuine crash.
    try:
        from funda.src.modules import maybe_resume_run
        if maybe_resume_run():
            logger.info("✓ Funda: auto-resumed interrupted scrape from saved state")
    except Exception as e:
        logger.warning(f"⚠ Funda auto-resume check failed: {e}")

    yield
    
    # Shutdown
    logger.info("Shutting down Automation Platform API...")
    await close_db()
    logger.info("✓ Cleanup complete")


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
    ## Data Info Automation Platform API
    
    **Funda Property Scraper** with real-time updates and RESTful API.
    
    ### Features
    - 🏠 **Funda Property Scraper** (Automated property data extraction)
    - 🔐 **JWT Authentication** (Secure user authentication)
    - 📡 **Real-time Updates** (WebSocket support for live progress)
    - 📊 **Google Sheets Integration** (Auto-save results)
    - 📈 **System Monitoring** (Health checks and performance metrics)
    
    ### Quick Start
    1. Register: `POST /api/v1/auth/register`
    2. Login: `POST /api/v1/auth/login` (get JWT token)
    3. Start Funda scraper: `POST /api/v1/funda/start`
    4. Monitor: `GET /api/v1/funda/status`
    """,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
    lifespan=lifespan
)

# CORS middleware - Allow all origins for local development
# Using JWT in Authorization header, not cookies, so credentials not needed
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

# Gzip compression
app.add_middleware(GZipMiddleware, minimum_size=1000)


# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Add response time to headers."""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


# Exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Validation error",
            "errors": exc.errors()
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "error": str(exc) if settings.DEBUG else "An unexpected error occurred"
        }
    )


# Include routers
app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(system.router, prefix=settings.API_PREFIX)
app.include_router(websocket.router, prefix=settings.API_PREFIX)
app.include_router(funda.router, prefix=settings.API_PREFIX)
app.include_router(properties.router, prefix=settings.API_PREFIX)
app.include_router(emails.router, prefix=settings.API_PREFIX)


# Root endpoint
@app.get("/")
async def root():
    """API root endpoint."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "docs": "/docs",
        "health": f"{settings.API_PREFIX}/system/health"
    }


@app.get("/health")
async def health():
    """Quick health check."""
    return {
        "status": "healthy",
        "version": settings.APP_VERSION
    }


# Development: Auto-reload notification
if settings.DEBUG:
    logger.warning("⚠️  DEBUG MODE ENABLED - Do not use in production!")
