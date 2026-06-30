"""
Database models for automation platform
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, JSON, Float, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum
from .database import Base


class JobStatus(str, enum.Enum):
    """Job execution status."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class JobPriority(str, enum.Enum):
    """Job execution priority."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ToolType(str, enum.Enum):
    """Available automation tools."""
    FUNDA = "funda"  # Funda property scraper


class User(Base):
    """User model for authentication."""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    jobs = relationship("Job", back_populates="user", cascade="all, delete-orphan")
    api_keys = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User {self.username}>"


class APIKey(Base):
    """API Key for programmatic access."""
    __tablename__ = "api_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    key_hash = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime)
    expires_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="api_keys")
    
    def __repr__(self):
        return f"<APIKey {self.name}>"


class Job(Base):
    """Job execution tracking."""
    __tablename__ = "jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Job identification
    job_uuid = Column(String, unique=True, index=True, nullable=False)
    tool_type = Column(SQLEnum(ToolType), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    
    # Job execution
    status = Column(SQLEnum(JobStatus), default=JobStatus.PENDING, index=True)
    priority = Column(SQLEnum(JobPriority), default=JobPriority.NORMAL)
    progress = Column(Float, default=0.0)  # 0-100
    
    # Input/Output
    input_file_path = Column(String)
    output_file_path = Column(String)
    display_filename = Column(String)  # User-friendly display name (may have duplicates)
    config = Column(JSON)  # Tool-specific configuration
    
    # Results
    total_rows = Column(Integer, default=0)
    processed_rows = Column(Integer, default=0)
    successful_rows = Column(Integer, default=0)
    failed_rows = Column(Integer, default=0)
    
    # Timing
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    estimated_completion = Column(DateTime)
    
    # Error handling
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)
    
    # Celery task tracking
    celery_task_id = Column(String, index=True)
    
    # Relationships
    user = relationship("User", back_populates="jobs")
    logs = relationship("JobLog", back_populates="job", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Job {self.job_uuid} - {self.status}>"


class JobLog(Base):
    """Detailed job execution logs."""
    __tablename__ = "job_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    level = Column(String, default="INFO")  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    message = Column(Text, nullable=False)
    log_metadata = Column(JSON)  # Additional structured data (renamed from 'metadata' to avoid SQLAlchemy conflict)
    
    # Relationships
    job = relationship("Job", back_populates="logs")
    
    def __repr__(self):
        return f"<JobLog {self.level} - {self.timestamp}>"


class SystemMetrics(Base):
    """System performance metrics for monitoring."""
    __tablename__ = "system_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Resource usage
    cpu_percent = Column(Float)
    memory_percent = Column(Float)
    disk_percent = Column(Float)
    
    # Job statistics
    active_jobs = Column(Integer, default=0)
    queued_jobs = Column(Integer, default=0)
    completed_jobs_today = Column(Integer, default=0)
    failed_jobs_today = Column(Integer, default=0)
    
    # Performance
    avg_job_duration = Column(Float)  # seconds
    success_rate = Column(Float)  # percentage
    
    def __repr__(self):
        return f"<SystemMetrics {self.timestamp}>"


class Property(Base):
    """
    Scraped Funda property record. Mirror of the 33-column Google Sheet,
    with a few CRM-friendly extras (email_status, notes, created/updated).
    Google Sheets stays the canonical write target of the scraper; this table
    is kept in sync (read-through + on-demand /properties/sync) so the
    Next.js dashboard can filter/sort fast and we can join emails to it.
    """
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, unique=True, index=True, nullable=False)

    # Sheet columns (33).
    scrape_date = Column(String)
    address = Column(String, index=True)
    listed_since = Column(String, index=True)
    days_on_market = Column(String)
    asking_price = Column(String)
    woz_value = Column(String)
    suggested_bid = Column(String)
    bidding_price = Column(String)
    price_per_m2 = Column(String)
    living_area = Column(String)
    plot_area = Column(String)
    rooms = Column(String)
    bedrooms = Column(String)
    construction_year = Column(String)
    property_type = Column(String, index=True)
    energy_label = Column(String, index=True)
    heating = Column(String)
    insulation = Column(String)
    maintenance_inside = Column(String)
    maintenance_outside = Column(String)
    garden = Column(String)
    garden_orientation = Column(String)
    parking = Column(String)
    vve = Column(String)
    erfpacht = Column(String)
    acceptance = Column(String)
    description = Column(Text)
    images = Column(Text)  # comma-separated URLs
    agency_name = Column(String, index=True)
    agency_phone = Column(String)
    agency_email = Column(String, index=True)
    agency_website = Column(String)

    # Source sheet tab the row originated from (e.g. '3-7 Days Ago').
    # Lets the dashboard filter by Funda publication-date bucket.
    sheet_tab = Column(String, index=True)

    # CRM extras.
    email_status = Column(String, default="not_sent", index=True)
    notes = Column(Text)
    # Manual/shuffled display order for the Global Data table (lower = first).
    # Null for freshly-scraped rows (shown last). Set by the shuffle op.
    display_order = Column(Integer, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_synced_at = Column(DateTime)

    # Relationship to emails.
    emails = relationship("EmailMessage", back_populates="property", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Property {self.address}>"


class EmailMessage(Base):
    """
    Email sent (or queued) to a property's agency. Dual storage: also mirrored
    into a Google Sheet tab by sheets_writer (Phase 4).
    """
    __tablename__ = "email_messages"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=True, index=True)
    property_url = Column(String, index=True)  # denormalized for safety

    to_email = Column(String, index=True, nullable=False)
    cc_emails = Column(String)
    subject = Column(String, nullable=False)
    body = Column(Text)            # plain-text part (fallback / record)
    body_html = Column(Text)       # HTML part — preferred when sending
    attachment_path = Column(String)

    status = Column(String, default="queued", index=True)  # queued|sent|failed|received
    error_message = Column(Text)

    # ── Chat-inbox threading (Gmail) ──────────────────────────
    direction = Column(String, default="outbound", index=True)  # outbound | inbound
    from_email = Column(String, index=True)        # sender (us=outbound, agency=inbound)
    gmail_message_id = Column(String, unique=True, index=True)   # Gmail API id (dedup key)
    gmail_thread_id = Column(String, index=True)   # conversation key
    rfc_message_id = Column(String, index=True)    # RFC822 Message-ID header
    in_reply_to = Column(String)                   # RFC822 Message-ID this replies to
    is_read = Column(Boolean, default=True, index=True)  # inbound rows inserted False

    sent_at = Column(DateTime, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    property = relationship("Property", back_populates="emails")
    attachments = relationship(
        "EmailAttachment", back_populates="email", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<EmailMessage to={self.to_email} status={self.status}>"


class EmailAttachment(Base):
    """A file attached to an email (inbound: downloaded from Gmail; outbound:
    uploaded in the reply composer). Bytes live on disk under ATTACHMENTS_DIR;
    this row is the metadata + path."""
    __tablename__ = "email_attachments"

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer, ForeignKey("email_messages.id"), nullable=False, index=True)
    filename = Column(String, nullable=False)
    mime_type = Column(String)
    size = Column(Integer)
    storage_path = Column(String)        # absolute path on disk
    gmail_attachment_id = Column(String) # Gmail attachment id (inbound)
    direction = Column(String, default="outbound")  # inbound | outbound
    created_at = Column(DateTime, default=datetime.utcnow)

    email = relationship("EmailMessage", back_populates="attachments")

    def __repr__(self):
        return f"<EmailAttachment {self.filename} email={self.email_id}>"


class GmailCredential(Base):
    """Stored OAuth2 tokens for the shared sender mailbox. One row per
    (email_address) — Gmail sends are performed on behalf of this
    account via the stored refresh_token. access_token is refreshed
    automatically by google-auth when expired."""
    __tablename__ = "gmail_credentials"

    id = Column(Integer, primary_key=True, index=True)
    email_address = Column(String, unique=True, index=True, nullable=False)
    refresh_token = Column(Text, nullable=False)
    access_token = Column(Text)
    token_expiry = Column(DateTime)
    scopes = Column(String)  # space-separated
    client_id = Column(String)
    client_secret = Column(String)
    token_uri = Column(String, default="https://oauth2.googleapis.com/token")
    last_history_id = Column(String)  # Gmail historyId watermark for inbox polling
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<GmailCredential {self.email_address}>"


class ToolConfig(Base):
    """Tool-specific configuration presets."""
    __tablename__ = "tool_configs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    tool_type = Column(SQLEnum(ToolType), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    config = Column(JSON, nullable=False)
    is_default = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<ToolConfig {self.tool_type} - {self.name}>"
