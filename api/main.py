from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
import os
import shutil
import hashlib
import hmac
import secrets
import uuid
import json
import smtplib
import subprocess
from email.message import EmailMessage

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
from sqlalchemy import Boolean, Date, DateTime, String, Text, create_engine, delete, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./memoria.db")
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", "/mnt/aguirres-center"))
STORAGE_CAPACITY_BYTES = int(os.getenv("STORAGE_CAPACITY_BYTES", str(2_000_000_000_000)))
PROFILE_PICTURES_ROOT = MEDIA_ROOT / "profile pictures"
SOURCES_ROOT = Path(os.getenv("SOURCES_ROOT", "/home/vicho/videos-familia"))
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tif", ".tiff", ".avif"}
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
PROFILE_PICTURES_ROOT.mkdir(parents=True, exist_ok=True)
SOURCES_ROOT.mkdir(parents=True, exist_ok=True)
for media_directory in ("videos", "audios", "photos", "documents"):
    (MEDIA_ROOT / media_directory).mkdir(parents=True, exist_ok=True)
(MEDIA_ROOT / "stickers").mkdir(parents=True, exist_ok=True)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


class Base(DeclarativeBase):
    pass


class RenameScriptRequest(BaseModel):
    paths: list[str]


class Video(Base):
    __tablename__ = "videos"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(200))
    event_type: Mapped[str] = mapped_column(String(80), default="Otros")
    recorded_on: Mapped[date] = mapped_column(Date)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, default=None)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, default=None)
    people: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    filename: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    visibility: Mapped[str] = mapped_column(String(20), default="public")
    allowed_users: Mapped[str] = mapped_column(Text, default="")
    share_token: Mapped[str] = mapped_column(String(128), default="")
    media_type: Mapped[str] = mapped_column(String(20), default="video")
    album_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, default=None)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, default=None)
    slide_group_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, default=None)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, default=None)


class FaceAnnotation(Base):
    __tablename__ = "face_annotations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    video_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(120))
    person_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, default=None)
    x: Mapped[float] = mapped_column()
    y: Mapped[float] = mapped_column()
    width: Mapped[float] = mapped_column()
    height: Mapped[float] = mapped_column()


class Sticker(Base):
    __tablename__ = "stickers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(200))
    people: Mapped[str] = mapped_column(Text, default="")
    filename: Mapped[str] = mapped_column(String(255), default="")
    media_type: Mapped[str] = mapped_column(String(20), default="image")
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Album(Base):
    __tablename__ = "albums"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(200))
    event_type: Mapped[str] = mapped_column(String(80), default="Otros")
    recorded_on: Mapped[date] = mapped_column(Date)
    is_long_duration: Mapped[bool] = mapped_column(Boolean, default=False)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, default=None)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, default=None)
    people: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(200))
    event_type: Mapped[str] = mapped_column(String(80), default="Otros")
    event_date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text, default="")
    person: Mapped[str] = mapped_column(String(120), default="")
    recurrence: Mapped[str] = mapped_column(String(20), default="none")
    video_ids: Mapped[str] = mapped_column(Text, default="")
    album_ids: Mapped[str] = mapped_column(Text, default="")
    occurrence_data: Mapped[str] = mapped_column(Text, default="{}")


class Person(Base):
    __tablename__ = "people"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(120), unique=True)
    nickname: Mapped[str] = mapped_column(String(80), default="")
    photo: Mapped[str] = mapped_column(String(255), default="")


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(80), unique=True)
    color: Mapped[str] = mapped_column(String(20), default="#d4845b")


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="visitor")
    display_name: Mapped[str] = mapped_column(String(120))
    first_name: Mapped[str] = mapped_column(String(80), default="")
    last_name: Mapped[str] = mapped_column(String(80), default="")
    email: Mapped[str] = mapped_column(String(160), default="")
    rules_accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    can_modify_admin_memories: Mapped[bool] = mapped_column(Boolean, default=False)


class EditorChange(Base):
    __tablename__ = "editor_changes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    editor_id: Mapped[str] = mapped_column(String(36))
    video_id: Mapped[str] = mapped_column(String(36))
    proposed_data: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    decision_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(20), default="visitor")
    token: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AccessRequest(Base):
    __tablename__ = "access_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    requester_id: Mapped[str] = mapped_column(String(36))
    requester_name: Mapped[str] = mapped_column(String(120))
    requester_email: Mapped[str] = mapped_column(String(160))
    request_text: Mapped[str] = mapped_column(Text)
    original_filename: Mapped[str] = mapped_column(String(255), default="")
    upload_path: Mapped[str] = mapped_column(String(255), default="")
    upload_media_type: Mapped[str] = mapped_column(String(20), default="video")
    title: Mapped[str] = mapped_column(String(200), default="")
    event_type: Mapped[str] = mapped_column(String(80), default="Otros")
    recorded_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    people: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    album_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, default=None)
    visibility: Mapped[str] = mapped_column(String(20), default="public")
    allowed_users: Mapped[str] = mapped_column(Text, default="")
    decision_reason: Mapped[str] = mapped_column(Text, default="")
    decision_token: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36))
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class VideoCreate(BaseModel):
    title: str
    event_type: str = "Otros"
    recorded_on: date
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    people: list[str] = []
    description: str = ""
    visibility: str = "public"
    allowed_users: list[str] = []
    media_type: str = "video"
    album_id: Optional[str] = None

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def empty_date_to_none(cls, value):
        return None if value == "" else value


class VideoUpdate(VideoCreate):
    pass


class StickerUpdate(BaseModel):
    title: str
    people: list[str] = []


class LoginPayload(BaseModel):
    username: str
    password: str


class UserUpdate(BaseModel):
    username: str
    first_name: str
    last_name: str
    email: str
    current_password: str = ""
    new_password: str = ""


class InviteCreate(BaseModel):
    email: str
    role: str = "visitor"


class RegisterPayload(BaseModel):
    token: str
    username: str
    first_name: str
    last_name: str
    password: str


class AccessRequestCreate(BaseModel):
    request: str


class AccessRequestReview(BaseModel):
    title: str
    event_type: str = "Otros"
    recorded_on: date
    people: list[str] = []
    description: str = ""
    album_id: Optional[str] = None
    visibility: str = "public"
    allowed_users: list[str] = []
    rejection_reason: str = ""


class VideoAccess(BaseModel):
    visibility: str = "public"
    allowed_users: list[str] = []


class PersonCreate(BaseModel):
    name: str
    nickname: str = ""


class PersonUpdate(BaseModel):
    name: str
    nickname: str = ""


class AlbumCreate(BaseModel):
    title: str
    recorded_on: Optional[date] = None
    is_long_duration: bool = False
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    event_type: str = "Otros"
    people: list[str] = []
    description: str = ""

    @field_validator("recorded_on", "start_date", "end_date", mode="before")
    @classmethod
    def empty_date_to_none(cls, value):
        return None if value == "" else value


class FaceAnnotationPayload(BaseModel):
    name: str
    person_id: Optional[str] = None
    x: float
    y: float
    width: float
    height: float


class CalendarEventCreate(BaseModel):
    title: str
    event_type: str = "Otros"
    event_date: date
    description: str = ""
    person: str = ""
    recurrence: str = "none"
    video_ids: list[str] = []
    album_ids: list[str] = []
    occurrence_year: Optional[int] = None


class CategoryCreate(BaseModel):
    name: str
    color: str = "#d4845b"


app = FastAPI(
    title="Memoria API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"{salt.hex()}${digest.hex()}"


def password_matches(password: str, stored: str) -> bool:
    salt_hex, digest_hex = stored.split("$", 1)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 310_000)
    return hmac.compare_digest(digest.hex(), digest_hex)


def current_user(request: Request) -> User:
    token = request.cookies.get("memoria_session")
    if not token:
        raise HTTPException(status_code=401, detail="Inicia sesión para continuar")
    with Session(engine) as session:
        login = session.get(LoginSession, token)
        if not login or login.expires_at < datetime.utcnow():
            raise HTTPException(status_code=401, detail="La sesión ha expirado")
        user = session.get(User, login.user_id)
        if not user:
            raise HTTPException(status_code=401, detail="Usuario no encontrado")
        return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Solo los administradores pueden modificar recuerdos")
    return user


def editor_user(user: User = Depends(current_user)) -> User:
    if user.role not in {"admin", "editor"}:
        raise HTTPException(status_code=403, detail="Solo administradores y editores pueden modificar recuerdos")
    if user.role == "editor" and not user.rules_accepted_at:
        raise HTTPException(status_code=403, detail="Debes aceptar las reglas de los editores antes de subir o modificar recuerdos")
    return user


def staff_user(user: User = Depends(current_user)) -> User:
    if user.role not in {"admin", "editor"}:
        raise HTTPException(status_code=403, detail="Solo administradores y editores pueden consultar los usuarios")
    return user


def content_manager(user: User = Depends(current_user)) -> User:
    if user.role not in {"admin", "editor"}:
        raise HTTPException(status_code=403, detail="Solo administradores y editores pueden administrar contenido")
    if user.role == "editor" and not user.rules_accepted_at:
        raise HTTPException(status_code=403, detail="Debes aceptar las reglas de los editores antes de administrar contenido")
    return user


def user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "name": user.display_name,
        "firstName": user.first_name,
        "lastName": user.last_name,
        "email": user.email,
        "role": user.role,
        "rulesAccepted": bool(user.rules_accepted_at),
        "canModifyAdminMemories": bool(user.can_modify_admin_memories),
    }


def send_invitation(email: str, token: str, role: str) -> None:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    sender = os.getenv("SMTP_FROM")
    if not host or not sender:
        raise HTTPException(status_code=503, detail="SMTP no está configurado")
    message = EmailMessage()
    app_url = os.getenv("APP_URL", "http://localhost:1234").rstrip("/")
    registration_url = f"{app_url}/?invite={token}"
    is_editor = role == "editor"
    message["Subject"] = (
        "Has sido invitado a Centro de los TULA AGUIRRES como editor"
        if is_editor
        else "Has sido invitado a Centro de los TULA AGUIRRES"
    )
    message["From"] = sender
    message["To"] = email
    message.set_content(
        (
            "Has sido invitado al Centro de los TULA AGUIRRES como editor.\n\n"
            "Vas a poder subir recuerdos a la plataforma. Recuerda seguir las reglas para editores.\n\n"
            f"Regístrate aquí: {registration_url}"
        )
        if is_editor
        else f"Has sido invitado a Centro de los TULA AGUIRRES.\n\nRegístrate aquí: {registration_url}"
    )
    invitation_copy = (
        "<p style=\"font-size:16px\">Has sido invitado al Centro de los TULA AGUIRRES como editor.</p>"
        "<p style=\"font-size:15px\">Vas a poder subir recuerdos a la plataforma. Recuerda seguir las reglas para editores.</p>"
        if is_editor
        else '<p style="font-size:16px">Has sido invitado a formar parte del archivo familiar.</p>'
    )
    message.add_alternative(
        f"""<html><body style="margin:0;background:#f8f7f3;font-family:Arial,sans-serif;color:#303a36">
        <div style="max-width:560px;margin:32px auto;background:#fff;border:1px solid #eeece6;border-radius:16px;overflow:hidden">
        <img src="cid:aguirres-logo" alt="Centro de los TULA AGUIRRES" style="display:block;width:100%;max-height:230px;object-fit:contain;background:#f0f0ec">
        <div style="padding:32px;text-align:center">        <div style="font-size:13px;letter-spacing:3px;color:#8f9691">CENTRO DE LOS TULA</div>
        <div style="font-size:32px;letter-spacing:4px;font-weight:700;color:#303a36;margin:6px 0 24px">AGUIRRES</div>
        {invitation_copy}
        <a href="{registration_url}" style="display:inline-block;margin-top:12px;padding:13px 22px;background:#d4845b;color:#fff;text-decoration:none;border-radius:8px;font-weight:bold">Registrarme</a>
        </div></div></body></html>""",
        subtype="html",
    )
    logo_path = Path(os.getenv("EMAIL_LOGO_PATH", "/app/email-assets/logo.png"))
    if not logo_path.is_file():
        logo_path = Path(__file__).resolve().parents[1] / "web" / "public" / "logo.png"
    if logo_path.is_file():
        message.get_payload()[-1].add_related(logo_path.read_bytes(), maintype="image", subtype="png", cid="<aguirres-logo>")
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        if os.getenv("SMTP_TLS", "true").lower() == "true":
            smtp.starttls()
        smtp.login(os.getenv("SMTP_USER", sender), os.getenv("SMTP_PASSWORD", ""))
        smtp.send_message(message)


def send_access_request_email(access_request: AccessRequest, admin_emails: list[str]) -> None:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    sender = os.getenv("SMTP_FROM")
    if not host or not sender:
        raise HTTPException(status_code=503, detail="SMTP no está configurado")
    app_url = os.getenv("APP_URL", "http://localhost:1234").rstrip("/")
    review_url = f"{app_url}/?review={access_request.id}"
    file_url = f"{app_url}/api/access-requests/{access_request.decision_token}/file"
    message = EmailMessage()
    message["Subject"] = f"Solicitud para agregar un recuerdo: {access_request.requester_name}"
    message["From"] = sender
    message["To"] = ", ".join(admin_emails)
    message.set_content(
        f"Nombre: {access_request.requester_name}\nCorreo: {access_request.requester_email}\n"
        f"Razón: {access_request.request_text}\nArchivo: {access_request.original_filename}\n\n"
        f"Ver archivo: {file_url}\nRevisar y clasificar: {review_url}"
    )
    message.add_alternative(
        f"""<html><body style="font-family:Arial,sans-serif;color:#303a36">
        <h2>Solicitud para agregar un recuerdo</h2>
        <p><b>Nombre:</b> {access_request.requester_name}</p>
        <p><b>Correo:</b> {access_request.requester_email}</p>
        <p><b>Razón:</b> {access_request.request_text}</p>
        <p><b>Archivo:</b> {access_request.original_filename}</p>
        <p><a href="{file_url}">Ver archivo</a></p>
        <p><a href="{review_url}" style="display:inline-block;padding:12px 18px;background:#6c956f;color:#fff;text-decoration:none;border-radius:6px">Revisar y clasificar</a></p>
        </body></html>""",
        subtype="html",
    )
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        if os.getenv("SMTP_TLS", "true").lower() == "true":
            smtp.starttls()
        smtp.login(os.getenv("SMTP_USER", sender), os.getenv("SMTP_PASSWORD", ""))
        smtp.send_message(message)


def send_access_decision_email(access_request: AccessRequest) -> None:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    sender = os.getenv("SMTP_FROM")
    if not host or not sender:
        raise HTTPException(status_code=503, detail="SMTP no está configurado")
    decision = "aceptada" if access_request.status == "accepted" else "rechazada"
    message = EmailMessage()
    message["Subject"] = f"Tu solicitud fue {decision}"
    message["From"] = sender
    message["To"] = access_request.requester_email
    message.set_content(
        f"Hola {access_request.requester_name},\n\nTu solicitud para agregar un recuerdo fue {decision}."
        + (f"\n\nRazón: {access_request.decision_reason}" if access_request.decision_reason else "")
    )
    with smtplib.SMTP(host, port, timeout=15) as smtp:
        if os.getenv("SMTP_TLS", "true").lower() == "true":
            smtp.starttls()
        smtp.login(os.getenv("SMTP_USER", sender), os.getenv("SMTP_PASSWORD", ""))
        smtp.send_message(message)


@app.post("/api/auth/login")
def login(payload: LoginPayload, response: Response) -> dict:
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.username == payload.username))
        if not user or not password_matches(payload.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
        token = secrets.token_urlsafe(48)
        session.add(LoginSession(token=token, user_id=user.id, expires_at=datetime.utcnow() + timedelta(days=7)))
        session.commit()
        response.set_cookie("memoria_session", token, httponly=True, samesite="lax", max_age=604800)
        return user_dict(user)


@app.post("/api/users/invite")
def invite_user(payload: InviteCreate, _: User = Depends(admin_user)) -> dict:
        if payload.role not in {"visitor", "editor", "admin"}:
            raise HTTPException(status_code=400, detail="Rol no válido")
        token = secrets.token_urlsafe(48)
        with Session(engine) as session:
            if session.scalar(select(User).where(User.email == payload.email)):
                raise HTTPException(status_code=409, detail="Ese correo ya está registrado")
            if session.scalar(select(Invitation).where(Invitation.email == payload.email, Invitation.accepted_at.is_(None))):
                raise HTTPException(status_code=409, detail="Ese correo ya tiene una invitación pendiente")
            invitation = Invitation(email=payload.email, role=payload.role, token=token)
            session.add(invitation)
            session.commit()
            try:
                send_invitation(payload.email, token, payload.role)
            except Exception as error:
                session.delete(invitation)
                session.commit()
                raise HTTPException(status_code=503, detail=f"No se pudo enviar el correo: {error}") from error
            return {"email": payload.email}


@app.get("/api/users/invitations")
def list_invitations(_: User = Depends(admin_user)) -> list[dict]:
    with Session(engine) as session:
        return [
            {"id": invitation.id, "email": invitation.email, "role": invitation.role, "createdAt": invitation.created_at.isoformat()}
            for invitation in session.scalars(
                select(Invitation).where(Invitation.accepted_at.is_(None)).order_by(Invitation.created_at.desc())
            )
        ]


@app.delete("/api/users/invitations/{invitation_id}")
def delete_invitation(invitation_id: str, _: User = Depends(admin_user)) -> dict:
    with Session(engine) as session:
        invitation = session.get(Invitation, invitation_id)
        if not invitation:
            raise HTTPException(status_code=404, detail="Invitación no encontrada")
        session.delete(invitation)
        session.commit()
        return {"ok": True}


@app.post("/api/access-requests")
async def create_access_request(
    request: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(current_user),
) -> dict:
    request_text = request.strip()
    if not request_text:
        raise HTTPException(status_code=400, detail="Escribe qué recuerdo quieres agregar")
    if not user.email.strip():
        raise HTTPException(status_code=400, detail="Agrega tu correo en Configuración antes de solicitar permiso")
    with Session(engine) as session:
        pending = session.scalar(
            select(AccessRequest).where(
                AccessRequest.requester_id == user.id,
                AccessRequest.status == "pending",
            )
        )
        if pending:
            raise HTTPException(status_code=409, detail="Ya tienes una solicitud pendiente")
        admins = [admin.email.strip() for admin in session.scalars(select(User).where(User.role == "admin")) if admin.email.strip()]
        if not admins:
            raise HTTPException(status_code=503, detail="No hay correos de administradores configurados")
        media_type = detected_media_type(file.filename or "media", file.content_type or "")
        pending_directory = MEDIA_ROOT / "pending-uploads"
        pending_directory.mkdir(parents=True, exist_ok=True)
        safe_name = f"{uuid.uuid4()}_{Path(file.filename or 'media').name}"
        pending_path = pending_directory / safe_name
        with pending_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        access_request = AccessRequest(
            requester_id=user.id,
            requester_name=user.display_name,
            requester_email=user.email.strip(),
            request_text=request_text,
            original_filename=file.filename or "media",
            upload_path=str(pending_path.relative_to(MEDIA_ROOT)),
            upload_media_type=media_type,
            decision_token=secrets.token_urlsafe(48),
        )
        session.add(access_request)
        session.commit()
        session.refresh(access_request)
        try:
            send_access_request_email(access_request, admins)
        except Exception as error:
            session.delete(access_request)
            session.commit()
            if pending_path.is_file():
                pending_path.unlink()
            raise HTTPException(status_code=503, detail=f"No se pudo enviar la solicitud: {error}") from error
        return {"status": access_request.status}


@app.get("/api/access-requests")
def list_access_requests(_: User = Depends(admin_user)) -> list[dict]:
    with Session(engine) as session:
        return [
            {
                "id": item.id,
                "name": item.requester_name,
                "email": item.requester_email,
                "reason": item.request_text,
                "filename": item.original_filename,
                "mediaType": item.upload_media_type,
                "status": item.status,
                "createdAt": item.created_at.isoformat(),
                "fileUrl": f"/api/access-requests/{item.decision_token}/file",
            }
            for item in session.scalars(select(AccessRequest).order_by(AccessRequest.created_at.desc()))
        ]


@app.get("/api/access-requests/{token}/file")
def access_request_file(token: str, request: Request) -> FileResponse:
    with Session(engine) as session:
        access_request = session.scalar(select(AccessRequest).where(AccessRequest.decision_token == token))
        if not access_request:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        token_user = request.cookies.get("memoria_session")
        login = session.get(LoginSession, token_user) if token_user else None
        login_user = session.get(User, login.user_id) if login else None
        is_admin = bool(login_user and login_user.role == "admin")
        if not is_admin and access_request.status != "pending":
            raise HTTPException(status_code=404, detail="Archivo no disponible")
        target = (MEDIA_ROOT / access_request.upload_path).resolve()
        if MEDIA_ROOT.resolve() not in target.parents or not target.is_file():
            raise HTTPException(status_code=404, detail="Archivo no encontrado")
        return FileResponse(target, filename=access_request.original_filename)


@app.post("/api/access-requests/{request_id}/approve")
def approve_access_request(request_id: str, payload: AccessRequestReview, _: User = Depends(admin_user)) -> dict:
    with Session(engine) as session:
        access_request = session.get(AccessRequest, request_id)
        if not access_request or access_request.status != "pending":
            raise HTTPException(status_code=404, detail="Solicitud no encontrada o ya atendida")
        title = payload.title.strip()
        source = (MEDIA_ROOT / access_request.upload_path).resolve()
        if not title or not source.is_file():
            raise HTTPException(status_code=400, detail="El título y el archivo son obligatorios")
        album = session.get(Album, payload.album_id) if payload.album_id else None
        if payload.album_id and not album:
            raise HTTPException(status_code=404, detail="Álbum no encontrado")
        recorded_on = payload.recorded_on
        event_type = payload.event_type.strip() or "Otros"
        if album and not album.is_long_duration:
            recorded_on = album.recorded_on
            event_type = album.event_type
        target = media_target(access_request.original_filename, access_request.upload_media_type, recorded_on)
        shutil.move(str(source), str(target))
        video = Video(
            title=title,
            event_type=event_type,
            recorded_on=recorded_on,
            people=", ".join(dict.fromkeys(payload.people)),
            description=payload.description.strip(),
            filename=str(target.relative_to(MEDIA_ROOT)),
            visibility=payload.visibility if payload.visibility in {"public", "restricted"} else "public",
            allowed_users=allowed_user_ids(session, ",".join(payload.allowed_users)),
            media_type=access_request.upload_media_type,
            album_id=payload.album_id or None,
        )
        session.add(video)
        access_request.status = "accepted"
        access_request.title = title
        access_request.event_type = event_type
        access_request.recorded_on = recorded_on
        access_request.people = video.people
        access_request.description = video.description
        access_request.album_id = payload.album_id
        access_request.visibility = video.visibility
        access_request.allowed_users = video.allowed_users
        access_request.decided_at = datetime.utcnow()
        session.commit()
        send_access_decision_email(access_request)
        return {"ok": True}


@app.post("/api/access-requests/{request_id}/reject")
def reject_access_request(request_id: str, payload: AccessRequestReview, _: User = Depends(admin_user)) -> dict:
    reason = payload.rejection_reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Escribe una razón para rechazar la solicitud")
    with Session(engine) as session:
        access_request = session.get(AccessRequest, request_id)
        if not access_request or access_request.status != "pending":
            raise HTTPException(status_code=404, detail="Solicitud no encontrada o ya atendida")
        access_request.status = "rejected"
        access_request.decision_reason = reason
        access_request.decided_at = datetime.utcnow()
        session.commit()
        send_access_decision_email(access_request)
        return {"ok": True}


@app.post("/api/auth/register")
def register(payload: RegisterPayload, response: Response) -> dict:
    first_name = payload.first_name.strip()
    last_name = payload.last_name.strip()
    username = payload.username.strip().lower()
    if not first_name or not last_name or not username or len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Completa usuario, nombre, apellido y una contraseña de al menos 8 caracteres")
    with Session(engine) as session:
        invitation = session.scalar(select(Invitation).where(Invitation.token == payload.token, Invitation.accepted_at.is_(None)))
        if not invitation:
            raise HTTPException(status_code=400, detail="La invitación no es válida o ya fue utilizada")
        if session.scalar(select(User).where(User.username == username)):
            raise HTTPException(status_code=409, detail="Ese nombre de usuario ya está registrado")
        if session.scalar(select(User).where(User.email == invitation.email)):
            raise HTTPException(status_code=409, detail="Ese correo ya está registrado")
        user = User(
            username=username,
            display_name=f"{first_name} {last_name}",
            first_name=first_name,
            last_name=last_name,
            email=invitation.email,
            role=invitation.role,
            password_hash=password_hash(payload.password),
        )
        session.add(user)
        invitation.accepted_at = datetime.utcnow()
        session.flush()
        session_token = secrets.token_urlsafe(48)
        session.add(LoginSession(token=session_token, user_id=user.id, expires_at=datetime.utcnow() + timedelta(days=7)))
        session.commit()
        response.set_cookie("memoria_session", session_token, httponly=True, samesite="lax", max_age=604800)
        return user_dict(user)


@app.post("/api/auth/accept-editor-rules")
def accept_editor_rules(response: Response, user: User = Depends(current_user)) -> dict:
    if user.role != "editor":
        return user_dict(user)
    with Session(engine) as session:
        stored = session.get(User, user.id)
        stored.rules_accepted_at = datetime.utcnow()
        session.commit()
        session.refresh(stored)
        return user_dict(stored)


@app.get("/api/users")
def list_users(_: User = Depends(editor_user)) -> list[dict]:
        with Session(engine) as session:
            return [user_dict(user) for user in session.scalars(select(User).order_by(User.display_name))]


@app.get("/api/registered-users")
def list_registered_users(_: User = Depends(staff_user)) -> list[dict]:
    with Session(engine) as session:
        return [
            {"id": user.id, "name": user.display_name, "email": user.email, "role": user.role}
            for user in session.scalars(select(User).where(User.role.in_({"visitor", "editor"})).order_by(User.display_name))
        ]


@app.delete("/api/users/{user_id}")
def delete_user(user_id: str, user: User = Depends(admin_user)) -> dict:
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propia cuenta")
    with Session(engine) as session:
        target = session.get(User, user_id)
        if not target:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        session.query(LoginSession).filter(LoginSession.user_id == user_id).delete()
        session.delete(target)
        session.commit()
        return {"ok": True}


@app.get("/api/editors")
def list_editor_contributions(_: User = Depends(admin_user)) -> list[dict]:
    with Session(engine) as session:
        editors = list(session.scalars(select(User).where(User.role == "editor").order_by(User.display_name)))
        videos = list(session.scalars(select(Video).order_by(Video.recorded_on.desc())))
        changes = list(session.scalars(select(EditorChange).order_by(EditorChange.created_at.desc())))
        editor_names = {editor.id: editor.display_name for editor in editors}
        video_map = {video.id: video for video in videos}
        return [
            {
                **user_dict(editor),
                "contributions": [video_dict(video) for video in videos if video.created_by == editor.id],
                "changes": [
                    {
                        "id": change.id,
                        "status": change.status,
                        "createdAt": change.created_at.isoformat(),
                        "decidedAt": change.decided_at.isoformat() if change.decided_at else None,
                        "decisionReason": change.decision_reason,
                        "video": video_dict(video_map[change.video_id]),
                        "proposed": json.loads(change.proposed_data),
                    }
                    for change in changes
                    if change.editor_id == editor.id and change.video_id in video_map
                ],
            }
            for editor in editors
        ]


class EditorPermissionUpdate(BaseModel):
    can_modify_admin_memories: bool


class EditorChangeDecision(BaseModel):
    reason: str = ""


@app.put("/api/editors/{editor_id}/permission")
def update_editor_permission(editor_id: str, payload: EditorPermissionUpdate, _: User = Depends(admin_user)) -> dict:
    with Session(engine) as session:
        editor = session.get(User, editor_id)
        if not editor or editor.role != "editor":
            raise HTTPException(status_code=404, detail="Editor no encontrado")
        editor.can_modify_admin_memories = payload.can_modify_admin_memories
        session.commit()
        session.refresh(editor)
        return user_dict(editor)


@app.post("/api/editor-changes/{change_id}/approve")
def approve_editor_change(change_id: str, _: User = Depends(admin_user)) -> dict:
    with Session(engine) as session:
        change = session.get(EditorChange, change_id)
        if not change or change.status != "pending":
            raise HTTPException(status_code=404, detail="Propuesta no encontrada o ya atendida")
        video = session.get(Video, change.video_id)
        if not video:
            raise HTTPException(status_code=404, detail="Recuerdo no encontrado")
        data = json.loads(change.proposed_data)
        validate_date_range(date.fromisoformat(data["start_date"]) if data.get("start_date") else None, date.fromisoformat(data["end_date"]) if data.get("end_date") else None)
        video.title = data["title"]
        video.event_type = data["event_type"]
        video.recorded_on = date.fromisoformat(data["recorded_on"])
        video.start_date = date.fromisoformat(data["start_date"]) if data.get("start_date") else None
        video.end_date = date.fromisoformat(data["end_date"]) if data.get("end_date") else None
        video.people = ", ".join(data["people"])
        video.description = data["description"]
        video.visibility = data["visibility"]
        video.allowed_users = allowed_user_ids(session, ",".join(data["allowed_users"]))
        video.media_type = data["media_type"]
        video.album_id = data["album_id"] or None
        if video.album_id:
            album = session.get(Album, video.album_id)
            if not album:
                raise HTTPException(status_code=404, detail="Álbum no encontrado")
            if not album.is_long_duration:
                video.recorded_on = album.recorded_on
                video.event_type = album.event_type
                video.start_date = video.end_date = None
        change.status = "approved"
        change.decided_at = datetime.utcnow()
        session.commit()
        return {"ok": True, "video": video_dict(video)}


@app.post("/api/editor-changes/{change_id}/reject")
def reject_editor_change(change_id: str, payload: EditorChangeDecision, _: User = Depends(admin_user)) -> dict:
    with Session(engine) as session:
        change = session.get(EditorChange, change_id)
        if not change or change.status != "pending":
            raise HTTPException(status_code=404, detail="Propuesta no encontrada o ya atendida")
        change.status = "rejected"
        change.decision_reason = payload.reason.strip()
        change.decided_at = datetime.utcnow()
        session.commit()
        return {"ok": True}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get("memoria_session")
    if token:
        with Session(engine) as session:
            login = session.get(LoginSession, token)
            if login:
                session.delete(login)
                session.commit()
    response.delete_cookie("memoria_session")
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)) -> dict:
    return user_dict(user)


@app.put("/api/auth/me")
def update_me(payload: UserUpdate, user: User = Depends(current_user)) -> dict:
    with Session(engine) as session:
        stored = session.get(User, user.id)
        username = payload.username.strip().lower()
        if not username:
            raise HTTPException(status_code=400, detail="El nombre de usuario es obligatorio")
        duplicate_username = session.scalar(select(User).where(User.username == username, User.id != user.id))
        if duplicate_username:
            raise HTTPException(status_code=409, detail="Ese nombre de usuario ya está registrado")
        email = payload.email.strip()
        duplicate_email = session.scalar(select(User).where(User.email == email, User.id != user.id)) if email else None
        if duplicate_email:
            raise HTTPException(status_code=409, detail="Ese correo ya está registrado")
        if payload.new_password:
            if not payload.current_password or not password_matches(payload.current_password, stored.password_hash):
                raise HTTPException(status_code=400, detail="La contraseña actual no es correcta")
            stored.password_hash = password_hash(payload.new_password)
        stored.username = username
        stored.first_name = payload.first_name.strip()
        stored.last_name = payload.last_name.strip()
        stored.email = email
        stored.display_name = " ".join(filter(None, [stored.first_name, stored.last_name])) or stored.username
        session.commit()
        session.refresh(stored)
        return user_dict(stored)


@app.get("/api/", include_in_schema=False)
def api_home() -> RedirectResponse:
    return RedirectResponse(url="/api/docs")


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        columns = {column["name"] for column in inspect(engine).get_columns("users")}
        for column in ("first_name", "last_name", "email"):
            if column not in columns:
                session.execute(text(f"ALTER TABLE users ADD COLUMN {column} VARCHAR(160) NOT NULL DEFAULT ''"))
        video_columns = {column["name"] for column in inspect(engine).get_columns("videos")}
        for column, definition in (("visibility", "VARCHAR(20) NOT NULL DEFAULT 'public'"), ("allowed_users", "TEXT NOT NULL DEFAULT ''"), ("share_token", "VARCHAR(128) NOT NULL DEFAULT ''"), ("media_type", "VARCHAR(20) NOT NULL DEFAULT 'video'"), ("album_id", "VARCHAR(36)"), ("created_by", "VARCHAR(36)"), ("slide_group_id", "VARCHAR(36)"), ("content_hash", "VARCHAR(64)"), ("start_date", "DATE"), ("end_date", "DATE")):
            if column not in video_columns:
                session.execute(text(f"ALTER TABLE videos ADD COLUMN {column} {definition}"))
        album_columns = {column["name"] for column in inspect(engine).get_columns("albums")}
        if "event_type" not in album_columns:
            session.execute(text("ALTER TABLE albums ADD COLUMN event_type VARCHAR(80) NOT NULL DEFAULT 'Otros'"))
        for column in ("start_date", "end_date"):
            if column not in album_columns:
                session.execute(text(f"ALTER TABLE albums ADD COLUMN {column} DATE"))
        if "is_long_duration" not in album_columns:
            session.execute(text("ALTER TABLE albums ADD COLUMN is_long_duration BOOLEAN NOT NULL DEFAULT FALSE"))
        calendar_columns = {column["name"] for column in inspect(engine).get_columns("calendar_events")}
        if "occurrence_data" not in calendar_columns:
            session.execute(text("ALTER TABLE calendar_events ADD COLUMN occurrence_data TEXT NOT NULL DEFAULT '{}'"))
        user_columns = {column["name"] for column in inspect(engine).get_columns("users")}
        if "rules_accepted_at" not in user_columns:
            session.execute(text("ALTER TABLE users ADD COLUMN rules_accepted_at TIMESTAMP"))
        if "can_modify_admin_memories" not in user_columns:
            session.execute(text("ALTER TABLE users ADD COLUMN can_modify_admin_memories BOOLEAN NOT NULL DEFAULT FALSE"))
        person_columns = {column["name"] for column in inspect(engine).get_columns("people")}
        if "nickname" not in person_columns:
            session.execute(text("ALTER TABLE people ADD COLUMN nickname VARCHAR(80) NOT NULL DEFAULT ''"))
        request_columns = {column["name"] for column in inspect(engine).get_columns("access_requests")}
        request_definitions = {
            "original_filename": "VARCHAR(255) NOT NULL DEFAULT ''",
            "upload_path": "VARCHAR(255) NOT NULL DEFAULT ''",
            "upload_media_type": "VARCHAR(20) NOT NULL DEFAULT 'video'",
            "title": "VARCHAR(200) NOT NULL DEFAULT ''",
            "event_type": "VARCHAR(80) NOT NULL DEFAULT 'Otros'",
            "recorded_on": "DATE",
            "people": "TEXT NOT NULL DEFAULT ''",
            "description": "TEXT NOT NULL DEFAULT ''",
            "album_id": "VARCHAR(36)",
            "visibility": "VARCHAR(20) NOT NULL DEFAULT 'public'",
            "allowed_users": "TEXT NOT NULL DEFAULT ''",
            "decision_reason": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in request_definitions.items():
            if column not in request_columns:
                session.execute(text(f"ALTER TABLE access_requests ADD COLUMN {column} {definition}"))
        if not session.scalar(select(User).where(User.username == "vicho")):
            temporary_password = os.getenv("ADMIN_TEMP_PASSWORD", "Vicho2026!")
            session.add(User(username="vicho", display_name="Vicho", first_name="Vicho", last_name="", email="", role="admin", password_hash=password_hash(temporary_password)))
        default_categories = (("Cumpleaños", "#8c9b73"), ("Nacimiento", "#b9859b"), ("Defuncion", "#6f7370"))
        for name, color in default_categories:
            if not session.scalar(select(Category).where(Category.name == name)):
                session.add(Category(name=name, color=color))
        for person in session.scalars(select(Person)):
            if person.photo and not person.photo.startswith("profile pictures/"):
                source = (MEDIA_ROOT / person.photo).resolve()
                target = PROFILE_PICTURES_ROOT / Path(person.photo).name
                if source.is_file() and not target.exists():
                    shutil.move(str(source), str(target))
                if target.is_file():
                    person.photo = target.relative_to(MEDIA_ROOT).as_posix()
            if person.photo:
                photo_path = MEDIA_ROOT / person.photo
                try:
                    from PIL import Image, ImageOps
                    with Image.open(photo_path) as image:
                        image_format = image.format or "JPEG"
                        square = ImageOps.fit(image.convert("RGB"), (800, 800), method=Image.Resampling.LANCZOS)
                        square.save(photo_path, format=image_format if image_format in {"JPEG", "PNG", "WEBP"} else "JPEG")
                except (FileNotFoundError, OSError, ValueError):
                    pass
        session.commit()


def video_dict(video: Video) -> dict:
    media_type = video.media_type
    if Path(video.filename).suffix.lower() in {".mp4", ".avi", ".mov", ".mkv", ".webm", ".mpeg", ".mpg"}:
        media_type = "video"
    return {
        "id": video.id, "title": video.title, "eventType": video.event_type,
        "date": video.recorded_on.isoformat(),
        "startDate": video.start_date.isoformat() if video.start_date else None,
        "endDate": video.end_date.isoformat() if video.end_date else None,
        "people": [p.strip() for p in video.people.split(",") if p.strip()],
        "description": video.description, "filename": video.filename,
        "visibility": video.visibility, "allowedUsers": [item.strip() for item in video.allowed_users.split(",") if item.strip()],
        "shareToken": video.share_token,
        "mediaType": media_type,
        "albumId": video.album_id,
        "createdBy": video.created_by,
        "slideGroupId": video.slide_group_id,
    }


def grouped_video_dicts(videos: list[Video]) -> list[dict]:
    grouped: dict[str, dict] = {}
    result: list[dict] = []
    for video in videos:
        item = video_dict(video)
        if not video.slide_group_id:
            result.append(item)
            continue
        group = grouped.get(video.slide_group_id)
        if group:
            group["slides"].append(item)
        else:
            grouped[video.slide_group_id] = {**item, "slides": [item]}
            result.append(grouped[video.slide_group_id])
    return result


def face_annotation_dict(annotation: FaceAnnotation) -> dict:
    return {
        "id": annotation.id,
        "name": annotation.name,
        "personId": annotation.person_id,
        "x": annotation.x,
        "y": annotation.y,
        "width": annotation.width,
        "height": annotation.height,
    }


@app.get("/api/videos/{video_id}/face-annotations")
def list_face_annotations(video_id: str, _: User = Depends(admin_user)) -> list[dict]:
    with Session(engine) as session:
        video = session.get(Video, video_id)
        if not video:
            raise HTTPException(status_code=404, detail="Recuerdo no encontrado")
        return [face_annotation_dict(item) for item in session.scalars(select(FaceAnnotation).where(FaceAnnotation.video_id == video_id))]


@app.put("/api/videos/{video_id}/face-annotations")
def save_face_annotations(video_id: str, payload: list[FaceAnnotationPayload], _: User = Depends(admin_user)) -> list[dict]:
    with Session(engine) as session:
        video = session.get(Video, video_id)
        if not video:
            raise HTTPException(status_code=404, detail="Recuerdo no encontrado")
        if video.media_type != "image" and Path(video.filename).suffix.lower() not in IMAGE_EXTENSIONS:
            raise HTTPException(status_code=400, detail="Solo se pueden identificar personas en fotos")
        people_ids = {item.id for item in session.scalars(select(Person).where(Person.id.in_([item.person_id for item in payload if item.person_id])))}
        for item in payload:
            if not item.name.strip():
                raise HTTPException(status_code=400, detail="Cada recuadro debe tener un nombre")
            if not all(0 <= value <= 1 for value in (item.x, item.y, item.width, item.height)) or item.x + item.width > 1 or item.y + item.height > 1:
                raise HTTPException(status_code=400, detail="La posición de cada recuadro no es válida")
            if item.person_id and item.person_id not in people_ids:
                raise HTTPException(status_code=400, detail="La persona seleccionada no existe")
        session.execute(delete(FaceAnnotation).where(FaceAnnotation.video_id == video_id))
        annotations = [
            FaceAnnotation(
                video_id=video_id,
                name=item.name.strip(),
                person_id=item.person_id,
                x=item.x,
                y=item.y,
                width=item.width,
                height=item.height,
            )
            for item in payload
        ]
        session.add_all(annotations)
        session.commit()
        return [face_annotation_dict(item) for item in annotations]


def sticker_dict(sticker: Sticker) -> dict:
    return {
        "id": sticker.id,
        "title": sticker.title,
        "people": [item.strip() for item in sticker.people.split(",") if item.strip()],
        "filename": sticker.filename,
        "mediaType": sticker.media_type,
        "createdBy": sticker.created_by,
        "createdAt": sticker.created_at.isoformat(),
    }


def can_view(video: Video, user: User) -> bool:
    allowed_users = {item.strip() for item in video.allowed_users.split(",") if item.strip()}
    return user.role == "admin" or video.visibility == "public" or user.id in allowed_users


def can_manage_video(video: Video, user: User) -> bool:
    return user.role == "admin" or (
        user.role == "editor"
        and (video.created_by == user.id or user.can_modify_admin_memories)
    )


def can_directly_modify_video(video: Video, user: User) -> bool:
    return user.role == "admin" or (user.role == "editor" and video.created_by == user.id)


def editor_change_data(payload: VideoUpdate) -> dict:
    return {
        "title": payload.title,
        "event_type": payload.event_type,
        "recorded_on": payload.recorded_on.isoformat(),
        "start_date": payload.start_date.isoformat() if payload.start_date else None,
        "end_date": payload.end_date.isoformat() if payload.end_date else None,
        "people": payload.people,
        "description": payload.description,
        "visibility": payload.visibility,
        "allowed_users": payload.allowed_users,
        "media_type": payload.media_type,
        "album_id": payload.album_id,
    }


def validate_date_range(start_date: Optional[date], end_date: Optional[date]) -> None:
    if (start_date is None) != (end_date is None):
        raise HTTPException(status_code=400, detail="Debes indicar ambas fechas para un recuerdo de larga duración")
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=400, detail="La fecha final no puede ser anterior a la fecha inicial")


def allowed_user_ids(session: Session, value: str) -> str:
    ids = dict.fromkeys(item.strip() for item in value.split(",") if item.strip())
    registered = {user.id for user in session.scalars(select(User).where(User.id.in_(ids), User.role.in_({"visitor", "editor"})))}
    return ",".join(user_id for user_id in ids if user_id in registered)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/storage")
def storage(_: User = Depends(current_user)) -> dict:
    try:
        result = subprocess.run(
            ["du", "-sb", "--", str(MEDIA_ROOT)],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        used_bytes = int(result.stdout.split()[0])
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError) as error:
        raise HTTPException(status_code=503, detail="No se pudo medir el almacenamiento") from error
    return {
        "path": str(MEDIA_ROOT),
        "usedBytes": used_bytes,
        "totalBytes": STORAGE_CAPACITY_BYTES,
    }


@app.get("/api/media/{filename:path}", response_model=None)
def media_file(filename: str, preview: int = 0, _: User = Depends(current_user)) -> FileResponse | Response:
    target = (MEDIA_ROOT / filename).resolve()
    if MEDIA_ROOT.resolve() not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    if preview and target.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
        try:
            from io import BytesIO
            from PIL import Image, ImageOps

            cache_root = MEDIA_ROOT / ".previews"
            cache_root.mkdir(parents=True, exist_ok=True)
            stat = target.stat()
            cache_key = hashlib.sha256(f"{target}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()
            cached = cache_root / f"{cache_key}.jpg"
            if not cached.is_file():
                with Image.open(target) as original:
                    image = ImageOps.exif_transpose(original).convert("RGB")
                    image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
                    temporary = BytesIO()
                    image.save(temporary, format="JPEG", quality=60, optimize=True, progressive=True)
                cached.write_bytes(temporary.getvalue())
            return FileResponse(cached, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=500, detail="No se pudo preparar la vista previa") from error
    return FileResponse(target)


@app.get("/api/pdf-info/{filename:path}")
def pdf_info(filename: str, _: User = Depends(current_user)) -> dict:
    target = (MEDIA_ROOT / filename).resolve()
    if MEDIA_ROOT.resolve() not in target.parents or not target.is_file() or target.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="PDF no encontrado")
    try:
        result = subprocess.run(["pdfinfo", str(target)], check=True, capture_output=True, text=True, timeout=30)
        pages = next(int(line.split(":", 1)[1].strip()) for line in result.stdout.splitlines() if line.startswith("Pages:"))
        return {"pages": pages}
    except (FileNotFoundError, StopIteration, ValueError, subprocess.SubprocessError) as error:
        raise HTTPException(status_code=503, detail="No se pudo leer el PDF") from error


@app.get("/api/pdf-page/{filename:path}", response_model=None)
def pdf_page(filename: str, page: int = 1, _: User = Depends(current_user)) -> FileResponse:
    target = (MEDIA_ROOT / filename).resolve()
    if MEDIA_ROOT.resolve() not in target.parents or not target.is_file() or target.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="PDF no encontrado")
    if page < 1:
        raise HTTPException(status_code=400, detail="Página no válida")
    try:
        cache_root = MEDIA_ROOT / ".pdf-previews"
        cache_root.mkdir(parents=True, exist_ok=True)
        stat = target.stat()
        cache_key = hashlib.sha256(f"{target}:{stat.st_mtime_ns}:{stat.st_size}:{page}".encode()).hexdigest()
        cached = cache_root / f"{cache_key}.jpg"
        if not cached.is_file():
            subprocess.run(
                ["pdftoppm", "-f", str(page), "-l", str(page), "-singlefile", "-jpeg", "-jpegopt", "quality=72", "-scale-to", "1400", str(target), str(cached.with_suffix(""))],
                check=True,
                capture_output=True,
                timeout=60,
            )
        return FileResponse(cached, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})
    except (FileNotFoundError, subprocess.SubprocessError, OSError) as error:
        raise HTTPException(status_code=503, detail="No se pudo preparar la página del PDF") from error


@app.get("/api/videos")
def list_videos(search: Optional[str] = None, event_type: Optional[str] = None, media_type: Optional[str] = None, sort: str = "date_desc", _: User = Depends(current_user)) -> list[dict]:
    with Session(engine) as session:
        user = session.get(User, _.id)
        album_titles = {
            album.title.strip().casefold()
            for album in session.scalars(select(Album))
            if session.scalar(select(Video.id).where(Video.album_id == album.id).limit(1))
        }
        album_group_ids = {
            group_id
            for group_id in session.scalars(select(Video.slide_group_id).where(Video.album_id.is_not(None), Video.slide_group_id.is_not(None)))
        }
        videos = [
            video
            for video in session.scalars(select(Video).order_by(Video.recorded_on.desc(), Video.created_at.asc()))
            if not video.album_id and video.slide_group_id not in album_group_ids and video.title.strip().casefold() not in album_titles and can_view(video, user)
        ]
    if search:
        needle = search.lower()
        videos = [v for v in videos if needle in v.title.lower() or needle in v.people.lower() or needle in v.event_type.lower()]
    if event_type and event_type != "Todos":
        videos = [v for v in videos if v.event_type == event_type]
    if media_type and media_type != "Todos":
        videos = [v for v in videos if v.media_type == media_type]
    if sort == "date_asc":
        videos.sort(key=lambda video: video.recorded_on)
    elif sort == "title_asc":
        videos.sort(key=lambda video: video.title.lower())
    return grouped_video_dicts(videos)


@app.get("/api/albums")
def list_albums(user: User = Depends(current_user)) -> list[dict]:
    with Session(engine) as session:
        visible = {video.id: video_dict(video) for video in session.scalars(select(Video).order_by(Video.created_at.asc())) if can_view(video, user)}
        album_group_ids = {
            album.id: {
                group_id
                for group_id in session.scalars(select(Video.slide_group_id).where(Video.album_id == album.id, Video.slide_group_id.is_not(None)))
            }
            for album in session.scalars(select(Album))
        }
        return [
            {
                "id": album.id,
                "title": album.title,
                "eventType": album.event_type,
                "date": album.recorded_on.isoformat(),
                "isLongDuration": album.is_long_duration,
                "startDate": album.start_date.isoformat() if album.is_long_duration and album.start_date else None,
                "endDate": album.end_date.isoformat() if album.is_long_duration and album.end_date else None,
                "people": [item.strip() for item in album.people.split(",") if item.strip()],
                "description": album.description,
                "videos": [item for item in visible.values() if item["albumId"] == album.id or item["slideGroupId"] in album_group_ids.get(album.id, set())],
            }
            for album in session.scalars(select(Album).order_by(Album.recorded_on.desc()))
        ]


@app.post("/api/albums")
def create_album(payload: AlbumCreate, _: User = Depends(content_manager)) -> dict:
    with Session(engine) as session:
        start_date = payload.start_date if payload.is_long_duration else payload.recorded_on
        end_date = payload.end_date if payload.is_long_duration else None
        if not start_date:
            raise HTTPException(status_code=400, detail="El álbum necesita una fecha")
        if payload.is_long_duration:
            validate_date_range(start_date, end_date)
        album = Album(title=payload.title.strip(), event_type=payload.event_type.strip() or "Otros", recorded_on=start_date, is_long_duration=payload.is_long_duration, start_date=start_date if payload.is_long_duration else None, end_date=end_date, people=", ".join(payload.people), description=payload.description)
        if not album.title:
            raise HTTPException(status_code=400, detail="El álbum necesita un nombre")
        session.add(album)
        session.commit()
        session.refresh(album)
        return {"id": album.id, "title": album.title, "eventType": album.event_type, "date": album.recorded_on.isoformat(), "isLongDuration": album.is_long_duration, "startDate": album.start_date.isoformat() if album.start_date else None, "endDate": album.end_date.isoformat() if album.end_date else None, "people": payload.people, "description": album.description, "videos": []}


@app.put("/api/albums/{album_id}")
def update_album(album_id: str, payload: AlbumCreate, _: User = Depends(admin_user)) -> dict:
    with Session(engine) as session:
        album = session.get(Album, album_id)
        if not album:
            raise HTTPException(status_code=404, detail="Álbum no encontrado")
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="El álbum necesita un nombre")
        start_date = payload.start_date if payload.is_long_duration else payload.recorded_on
        end_date = payload.end_date if payload.is_long_duration else None
        if not start_date:
            raise HTTPException(status_code=400, detail="El álbum necesita una fecha")
        if payload.is_long_duration:
            validate_date_range(start_date, end_date)
        album.title = title
        album.event_type = payload.event_type.strip() or "Otros"
        album.recorded_on = start_date
        album.is_long_duration = payload.is_long_duration
        album.start_date = start_date if payload.is_long_duration else None
        album.end_date = end_date
        album.people = ", ".join(payload.people)
        album.description = payload.description
        session.commit()
        session.refresh(album)
        return {"id": album.id, "title": album.title, "eventType": album.event_type, "date": album.recorded_on.isoformat(), "isLongDuration": album.is_long_duration, "startDate": album.start_date.isoformat() if album.start_date else None, "endDate": album.end_date.isoformat() if album.end_date else None, "people": payload.people, "description": album.description}


@app.delete("/api/albums/{album_id}")
def delete_album(album_id: str, _: User = Depends(admin_user)) -> dict:
    with Session(engine) as session:
        album = session.get(Album, album_id)
        if not album:
            raise HTTPException(status_code=404, detail="Álbum no encontrado")
        for video in session.scalars(select(Video).where(Video.album_id == album_id)):
            video.album_id = None
        session.delete(album)
        session.commit()
    return {"ok": True}


def calendar_event_dict(event: CalendarEvent) -> dict:
    try:
        occurrence_overrides = json.loads(event.occurrence_data or "{}")
    except json.JSONDecodeError:
        occurrence_overrides = {}
    return {
        "id": event.id,
        "title": event.title,
        "eventType": event.event_type,
        "date": event.event_date.isoformat(),
        "description": event.description,
        "person": event.person,
        "recurrence": event.recurrence,
        "videoIds": [item for item in event.video_ids.split(",") if item],
        "albumIds": [item for item in event.album_ids.split(",") if item],
        "occurrenceOverrides": occurrence_overrides,
    }


@app.get("/api/calendar-events")
def list_calendar_events(_: User = Depends(current_user)) -> list[dict]:
    with Session(engine) as session:
        return [calendar_event_dict(event) for event in session.scalars(select(CalendarEvent).order_by(CalendarEvent.event_date))]


@app.post("/api/calendar-events")
def create_calendar_event(payload: CalendarEventCreate, _: User = Depends(admin_user)) -> dict:
    with Session(engine) as session:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="El evento necesita un nombre")
        if payload.event_type in {"Nacimiento", "Defuncion"} and not payload.person.strip():
            raise HTTPException(status_code=400, detail="Este evento debe estar asignado a una persona")
        recurrence = payload.recurrence if payload.recurrence in {"none", "annual"} else "none"
        event = CalendarEvent(
            title=title,
            event_type=payload.event_type.strip() or "Otros",
            event_date=payload.event_date,
            description=payload.description.strip(),
            person=payload.person.strip(),
            recurrence=recurrence,
            video_ids=",".join(dict.fromkeys(payload.video_ids)),
            album_ids=",".join(dict.fromkeys(payload.album_ids)),
        )
        session.add(event)
        session.commit()
        session.refresh(event)
        return calendar_event_dict(event)


@app.put("/api/calendar-events/{event_id}")
def update_calendar_event(event_id: str, payload: CalendarEventCreate, _: User = Depends(admin_user)) -> dict:
    with Session(engine) as session:
        event = session.get(CalendarEvent, event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Evento no encontrado")
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="El evento necesita un nombre")
        event_type = payload.event_type.strip() or "Otros"
        if event_type in {"Nacimiento", "Defuncion"} and not payload.person.strip():
            raise HTTPException(status_code=400, detail="Este evento debe estar asignado a una persona")
        if payload.occurrence_year and event.recurrence == "annual":
            try:
                occurrence_overrides = json.loads(event.occurrence_data or "{}")
            except json.JSONDecodeError:
                occurrence_overrides = {}
            occurrence_overrides[str(payload.occurrence_year)] = {
                "videoIds": list(dict.fromkeys(payload.video_ids)),
                "albumIds": list(dict.fromkeys(payload.album_ids)),
                "person": payload.person.strip(),
                "description": payload.description.strip(),
            }
            event.occurrence_data = json.dumps(occurrence_overrides)
            session.commit()
            session.refresh(event)
            return calendar_event_dict(event)
        event.title = title
        event.event_type = event_type
        event.event_date = payload.event_date
        event.description = payload.description.strip()
        event.person = payload.person.strip()
        event.recurrence = payload.recurrence if payload.recurrence in {"none", "annual"} else "none"
        event.video_ids = ",".join(dict.fromkeys(payload.video_ids))
        event.album_ids = ",".join(dict.fromkeys(payload.album_ids))
        session.commit()
        session.refresh(event)
        return calendar_event_dict(event)


@app.delete("/api/calendar-events/{event_id}")
def delete_calendar_event(event_id: str, _: User = Depends(admin_user)) -> dict:
    with Session(engine) as session:
        event = session.get(CalendarEvent, event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Evento no encontrado")
        session.delete(event)
        session.commit()
    return {"ok": True}


@app.post("/api/videos")
def create_video(payload: VideoCreate, _: User = Depends(admin_user)) -> dict:
    with Session(engine) as session:
        validate_date_range(payload.start_date, payload.end_date)
        album = session.get(Album, payload.album_id) if payload.album_id else None
        if payload.album_id and not album:
            raise HTTPException(status_code=404, detail="Álbum no encontrado")
        recorded_on = album.recorded_on if album and not album.is_long_duration else payload.recorded_on
        event_type = album.event_type if album and not album.is_long_duration else payload.event_type
        start_date, end_date = (None, None) if album and not album.is_long_duration else (payload.start_date, payload.end_date)
        video = Video(title=payload.title, event_type=event_type, recorded_on=recorded_on,
                      start_date=start_date, end_date=end_date,
                      people=", ".join(payload.people), description=payload.description,
                      visibility=payload.visibility, allowed_users=",".join(payload.allowed_users), media_type=payload.media_type, album_id=payload.album_id)
        session.add(video)
        session.commit()
        session.refresh(video)
        return video_dict(video)


@app.put("/api/videos/{video_id}")
def update_video(video_id: str, payload: VideoUpdate, user: User = Depends(editor_user)) -> dict:
    with Session(engine) as session:
        video = session.get(Video, video_id)
        if not video:
            raise HTTPException(status_code=404, detail="Recuerdo no encontrado")
        if not can_manage_video(video, user):
            raise HTTPException(status_code=403, detail="Solo puedes modificar tus propios recuerdos")
        validate_date_range(payload.start_date, payload.end_date)
        if user.role == "editor" and video.created_by != user.id:
            pending = session.scalar(select(EditorChange).where(
                EditorChange.video_id == video.id,
                EditorChange.editor_id == user.id,
                EditorChange.status == "pending",
            ))
            if pending:
                raise HTTPException(status_code=409, detail="Ya tienes una modificación pendiente para este recuerdo")
            session.add(EditorChange(
                editor_id=user.id,
                video_id=video.id,
                proposed_data=json.dumps(editor_change_data(payload)),
            ))
            session.commit()
            return {"pendingApproval": True, "message": "La modificación quedó pendiente de aprobación de un administrador"}
        if not can_directly_modify_video(video, user):
            raise HTTPException(status_code=403, detail="Los cambios de archivo requieren aprobación y por ahora solo puedes proponer cambios de datos")
        video.title, video.event_type, video.recorded_on = payload.title, payload.event_type, payload.recorded_on
        video.start_date, video.end_date = payload.start_date, payload.end_date
        video.people, video.description = ", ".join(payload.people), payload.description
        video.visibility = payload.visibility
        video.allowed_users = allowed_user_ids(session, ",".join(payload.allowed_users))
        video.media_type, video.album_id = payload.media_type, payload.album_id or None
        if video.album_id:
            album = session.get(Album, video.album_id)
            if not album:
                raise HTTPException(status_code=404, detail="Álbum no encontrado")
            if not album.is_long_duration:
                video.recorded_on = album.recorded_on
                video.event_type = album.event_type
                video.start_date = video.end_date = None
        session.commit()
        session.refresh(video)
        return video_dict(video)


@app.post("/api/videos/{video_id}/replace")
async def replace_video_file(video_id: str, file: UploadFile = File(...), user: User = Depends(editor_user)) -> dict:
    with Session(engine) as session:
        video = session.get(Video, video_id)
        if not video:
            raise HTTPException(status_code=404, detail="Recuerdo no encontrado")
        if not can_manage_video(video, user):
            raise HTTPException(status_code=403, detail="Solo puedes modificar tus propios recuerdos")
        if not can_directly_modify_video(video, user):
            raise HTTPException(status_code=403, detail="Los cambios de archivo requieren aprobación y por ahora solo puedes proponer cambios de datos")
        detected_type = detected_media_type(file.filename or "", file.content_type or "")
        if detected_type != video.media_type:
            raise HTTPException(status_code=400, detail=f"El archivo debe ser de tipo {video.media_type}")
        digest = content_hash(file.file)
        duplicate = existing_duplicate(session, digest, content_size(file.file), exclude_id=video.id)
        if duplicate:
            raise HTTPException(status_code=409, detail=f"El archivo ya está subido como '{duplicate.title}'")
        old_filename = video.filename
        new_filename = store_uploaded_file(file.file, file.filename or Path(old_filename).name, video.media_type, video.recorded_on)
        video.filename = new_filename
        video.content_hash = digest
        session.commit()
        session.refresh(video)
    if old_filename:
        old_target = MEDIA_ROOT / old_filename
        if old_target.is_file():
            old_target.unlink()
    return video_dict(video)


@app.post("/api/videos/{video_id}/slides")
async def add_video_slides(video_id: str, files: list[UploadFile] = File(...), user: User = Depends(editor_user)) -> dict:
    with Session(engine) as session:
        video = session.get(Video, video_id)
        if not video:
            raise HTTPException(status_code=404, detail="Slide no encontrado")
        if not can_manage_video(video, user):
            raise HTTPException(status_code=403, detail="Solo puedes modificar tus propios recuerdos")
        if video.media_type != "image" or not video.slide_group_id:
            raise HTTPException(status_code=400, detail="Solo los recuerdos de fotos pueden tener slides")
        if not files:
            raise HTTPException(status_code=400, detail="Selecciona al menos una foto")
        if any(Path(item.filename or "").suffix.lower() not in IMAGE_EXTENSIONS for item in files):
            raise HTTPException(status_code=400, detail="Los slides solo admiten archivos de imagen")
        hashes = []
        for item in files:
            digest = content_hash(item.file)
            duplicate = existing_duplicate(session, digest, content_size(item.file))
            if duplicate:
                raise HTTPException(status_code=409, detail=f"El archivo '{item.filename}' ya está subido como '{duplicate.title}'")
            if digest in hashes:
                raise HTTPException(status_code=409, detail=f"El archivo '{item.filename}' está repetido en la selección")
            hashes.append(digest)
        for item, digest in zip(files, hashes):
            filename = store_uploaded_file(item.file, item.filename or "slide.jpg", "image", video.recorded_on)
            session.add(Video(title=video.title, event_type=video.event_type, recorded_on=video.recorded_on,
                              people=video.people, description=video.description, filename=filename,
                              visibility=video.visibility, allowed_users=video.allowed_users,
                              media_type="image", album_id=video.album_id, created_by=video.created_by,
                              slide_group_id=video.slide_group_id, content_hash=digest))
        session.commit()
        return {"ok": True, "added": len(files)}


@app.delete("/api/videos/{video_id}/slide")
def delete_video_slide(video_id: str, user: User = Depends(editor_user)) -> dict:
    with Session(engine) as session:
        video = session.get(Video, video_id)
        if not video:
            raise HTTPException(status_code=404, detail="Slide no encontrado")
        if not can_manage_video(video, user):
            raise HTTPException(status_code=403, detail="Solo puedes eliminar tus propios recuerdos")
        if not can_directly_modify_video(video, user):
            raise HTTPException(status_code=403, detail="Los cambios de archivo requieren aprobación y por ahora solo puedes proponer cambios de datos")
        if not video.slide_group_id:
            raise HTTPException(status_code=400, detail="Este documento no es un slide")
        slides = list(session.scalars(select(Video).where(Video.slide_group_id == video.slide_group_id).order_by(Video.created_at, Video.id)))
        if len(slides) <= 1:
            raise HTTPException(status_code=400, detail="El recuerdo debe conservar al menos un slide")
        filename = video.filename
        session.delete(video)
        session.commit()
    if filename:
        target = MEDIA_ROOT / filename
        if target.is_file():
            target.unlink()
    return {"ok": True}


@app.delete("/api/videos/{video_id}")
def delete_video(video_id: str, user: User = Depends(editor_user)) -> dict:
    with Session(engine) as session:
        video = session.get(Video, video_id)
        if not video:
            raise HTTPException(status_code=404, detail="Recuerdo no encontrado")
        if not can_manage_video(video, user):
            raise HTTPException(status_code=403, detail="Solo puedes eliminar tus propios recuerdos")
        if not can_directly_modify_video(video, user):
            raise HTTPException(status_code=403, detail="Los cambios de archivo requieren aprobación y por ahora solo puedes proponer cambios de datos")
        group_videos = list(session.scalars(select(Video).where(Video.slide_group_id == video.slide_group_id))) if video.slide_group_id else [video]
        filenames = [item.filename for item in group_videos]
        for item in group_videos:
            session.delete(item)
        session.commit()
    for filename in filenames:
        target = MEDIA_ROOT / filename
        if target.is_file():
            target.unlink()
    return {"ok": True}


@app.post("/api/videos/{video_id}/share")
def create_share_link(video_id: str, _: User = Depends(admin_user)) -> dict:
    with Session(engine) as session:
        video = session.get(Video, video_id)
        if not video:
            raise HTTPException(status_code=404, detail="Recuerdo no encontrado")
        video.share_token = secrets.token_urlsafe(24)
        session.commit()
        return {"token": video.share_token}


@app.get("/api/shared/{token}")
def shared_video(token: str) -> dict:
    with Session(engine) as session:
        video = session.scalar(select(Video).where(Video.share_token == token))
        if not video:
            raise HTTPException(status_code=404, detail="Enlace no encontrado")
        return video_dict(video)


@app.post("/api/videos/upload")
async def upload_video(
    title: str = Form(...), event_type: str = Form("Otros"), recorded_on: date = Form(...),
    start_date: Optional[date] = Form(None), end_date: Optional[date] = Form(None),
    people: str = Form(""), description: str = Form(""), file: UploadFile = File(None),
    visibility: str = Form("public"), allowed_users: str = Form(""), media_type: str = Form("video"),
    album_id: str = Form(""), files: list[UploadFile] = File([]),
    user: User = Depends(editor_user),
) -> dict:
    validate_date_range(start_date, end_date)
    if file:
        files = [file, *files]
    if not files:
        raise HTTPException(status_code=400, detail="Selecciona al menos una foto")
    if len(files) > 1:
        if any(Path(item.filename or "").suffix.lower() not in IMAGE_EXTENSIONS for item in files):
            raise HTTPException(status_code=400, detail="Los slides múltiples solo admiten archivos de imagen")
        with Session(engine) as session:
            if not title.strip():
                raise HTTPException(status_code=400, detail="El recuerdo necesita un título")
            album = session.get(Album, album_id) if album_id else None
            if album_id and not album:
                raise HTTPException(status_code=404, detail="Álbum no encontrado")
            if album and not album.is_long_duration:
                recorded_on = album.recorded_on
                event_type = album.event_type
                start_date = end_date = None
            hashes = []
            for item in files:
                digest = content_hash(item.file)
                duplicate = existing_duplicate(session, digest, content_size(item.file))
                if duplicate:
                    raise HTTPException(status_code=409, detail=f"El archivo '{item.filename}' ya está subido como '{duplicate.title}'")
                if digest in hashes:
                    raise HTTPException(status_code=409, detail=f"El archivo '{item.filename}' está repetido en la selección")
                hashes.append(digest)
            slide_group_id = str(uuid.uuid4())
            for position, item in enumerate(files, start=1):
                safe_name = store_uploaded_file(item.file, item.filename or f"slide_{position}.jpg", "image", recorded_on)
                session.add(Video(title=title, event_type=event_type, recorded_on=recorded_on, start_date=start_date, end_date=end_date, people=people, description=description, filename=safe_name, visibility=visibility if visibility in {"public", "restricted"} else "public", allowed_users=allowed_user_ids(session, allowed_users), media_type="image", album_id=album.id if album else None, created_by=user.id, slide_group_id=slide_group_id, content_hash=hashes[position - 1]))
            session.commit()
            return {"title": title, "slides": len(files)}
    file = files[0]
    detected_type = detected_media_type(file.filename or "media", file.content_type or "")
    media_type = media_type if media_type in {"video", "audio", "image", "document", "letter"} else detected_type
    with Session(engine) as session:
        album = session.get(Album, album_id) if album_id else None
        if album_id and not album:
            raise HTTPException(status_code=404, detail="Álbum no encontrado")
        if album and not album.is_long_duration:
            recorded_on = album.recorded_on
            event_type = album.event_type
            start_date = end_date = None
        digest = content_hash(file.file)
        duplicate = existing_duplicate(session, digest, content_size(file.file))
        if duplicate:
            raise HTTPException(status_code=409, detail=f"El archivo ya está subido como '{duplicate.title}'")
        safe_name = store_uploaded_file(file.file, file.filename or "media", media_type, recorded_on)
        video = Video(title=title, event_type=event_type, recorded_on=recorded_on, start_date=start_date, end_date=end_date, people=people, description=description, filename=safe_name, visibility=visibility if visibility in {"public", "restricted"} else "public", allowed_users=allowed_user_ids(session, allowed_users), media_type=media_type, album_id=album_id or None, created_by=user.id, content_hash=digest)
        session.add(video)
        session.commit()
        session.refresh(video)
        return video_dict(video)


@app.get("/api/people")
def list_people(user: User = Depends(current_user)) -> list[dict]:
    with Session(engine) as session:
        videos = list(session.scalars(select(Video)))
        return [
            {
                "id": person.id,
                "name": person.name,
                "nickname": person.nickname,
                "photo": person.photo,
                "videos": grouped_video_dicts([
                    video
                    for video in videos
                    if person.name in {name.strip() for name in video.people.split(",") if name.strip()}
                    and can_view(video, user)
                ]),
            }
            for person in session.scalars(select(Person).order_by(Person.name))
        ]


@app.get("/api/stickers")
def list_stickers(_: User = Depends(editor_user)) -> list[dict]:
    with Session(engine) as session:
        return [sticker_dict(item) for item in session.scalars(select(Sticker).order_by(Sticker.created_at.desc()))]


@app.post("/api/stickers/upload")
async def upload_sticker(
    title: str = Form(""),
    people: str = Form(""),
    file: UploadFile = File(...),
    user: User = Depends(editor_user),
) -> dict:
    filename = file.filename or "sticker"
    media_type = detected_media_type(filename, file.content_type or "")
    if media_type != "image":
        raise HTTPException(status_code=400, detail="Los stickers deben ser fotos o GIFs")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        raise HTTPException(status_code=400, detail="Formato no compatible. Usa JPG, PNG, GIF o WEBP")
    safe_name = f"{uuid.uuid4().hex}{suffix}"
    target = MEDIA_ROOT / "stickers" / safe_name
    with target.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    with Session(engine) as session:
        sticker = Sticker(title=title.strip() or Path(filename).stem, people=people, filename=f"stickers/{safe_name}", media_type="image", created_by=user.id)
        session.add(sticker)
        session.commit()
        session.refresh(sticker)
        return sticker_dict(sticker)


@app.delete("/api/stickers/{sticker_id}")
def delete_sticker(sticker_id: str, user: User = Depends(editor_user)) -> dict:
    with Session(engine) as session:
        sticker = session.get(Sticker, sticker_id)
        if not sticker:
            raise HTTPException(status_code=404, detail="Sticker no encontrado")
        if user.role != "admin" and sticker.created_by != user.id:
            raise HTTPException(status_code=403, detail="Solo puedes eliminar tus propios stickers")
        filename = sticker.filename
        session.delete(sticker)
        session.commit()
    target = MEDIA_ROOT / filename
    if target.is_file():
        target.unlink()
    return {"ok": True}


@app.put("/api/stickers/{sticker_id}")
def update_sticker(sticker_id: str, payload: StickerUpdate, user: User = Depends(editor_user)) -> dict:
    with Session(engine) as session:
        sticker = session.get(Sticker, sticker_id)
        if not sticker:
            raise HTTPException(status_code=404, detail="Sticker no encontrado")
        if user.role != "admin" and sticker.created_by != user.id:
            raise HTTPException(status_code=403, detail="Solo puedes modificar tus propios stickers")
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="El sticker necesita un título")
        sticker.title = title
        sticker.people = ", ".join(dict.fromkeys(item.strip() for item in payload.people if item.strip()))
        session.commit()
        session.refresh(sticker)
        return sticker_dict(sticker)


@app.post("/api/people")
def create_person(payload: PersonCreate, _: User = Depends(content_manager)) -> dict:
    with Session(engine) as session:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="El nombre de la persona es obligatorio")
        if session.scalar(select(Person).where(Person.name == name)):
            raise HTTPException(status_code=409, detail="Esa persona ya existe")
        person = Person(name=name, nickname=payload.nickname.strip())
        session.add(person)
        session.commit()
        session.refresh(person)
        return {"id": person.id, "name": person.name, "nickname": person.nickname, "photo": person.photo}


@app.put("/api/people/{person_id}")
def update_person(person_id: str, payload: PersonUpdate, _: User = Depends(content_manager)) -> dict:
    with Session(engine) as session:
        person = session.get(Person, person_id)
        if not person:
            raise HTTPException(status_code=404, detail="Persona no encontrada")
        previous_name = person.name
        person.name = payload.name.strip()
        person.nickname = payload.nickname.strip()
        for video in session.scalars(select(Video)):
            names = [name.strip() for name in video.people.split(",") if name.strip()]
            if previous_name in names:
                video.people = ", ".join(payload.name.strip() if name == previous_name else name for name in names)
        session.commit()
        return {"id": person.id, "name": person.name, "nickname": person.nickname, "photo": person.photo}


@app.delete("/api/people/{person_id}")
def delete_person(person_id: str, _: User = Depends(admin_user)) -> dict:
    with Session(engine) as session:
        person = session.get(Person, person_id)
        if not person:
            raise HTTPException(status_code=404, detail="Persona no encontrada")
        name = person.name
        for video in session.scalars(select(Video)):
            video.people = ", ".join(item for item in video.people.split(",") if item.strip() != name)
        for album in session.scalars(select(Album)):
            album.people = ", ".join(item for item in album.people.split(",") if item.strip() != name)
        photo = person.photo
        session.delete(person)
        session.commit()
    if photo:
        target = MEDIA_ROOT / photo
        if target.is_file():
            target.unlink()
    return {"ok": True}


@app.post("/api/people/{person_id}/photo")
async def upload_person_photo(person_id: str, file: UploadFile = File(...), _: User = Depends(admin_user)) -> dict:
    safe_name = f"person_{uuid.uuid4()}_{Path(file.filename or 'photo').name}"
    target = PROFILE_PICTURES_ROOT / safe_name
    from PIL import Image, ImageOps
    try:
        image = Image.open(file.file).convert("RGB")
        image = ImageOps.fit(image, (800, 800), method=Image.Resampling.LANCZOS)
        target = target.with_suffix(".jpg")
        image.save(target, format="JPEG", quality=90)
    except Exception as error:
        raise HTTPException(status_code=400, detail="La foto no es válida") from error
    with Session(engine) as session:
        person = session.get(Person, person_id)
        if not person:
            raise HTTPException(status_code=404, detail="Persona no encontrada")
        person.photo = target.relative_to(MEDIA_ROOT).as_posix()
        session.commit()
        return {"id": person.id, "name": person.name, "photo": person.photo}


@app.get("/api/categories")
def list_categories(_: User = Depends(current_user)) -> list[dict]:
    with Session(engine) as session:
        return [{"id": c.id, "name": c.name, "color": c.color} for c in session.scalars(select(Category).order_by(Category.name))]


@app.post("/api/categories")
def create_category(payload: CategoryCreate, _: User = Depends(admin_user)) -> dict:
    with Session(engine) as session:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="El tipo de evento es obligatorio")
        if session.scalar(select(Category).where(Category.name == name)):
            raise HTTPException(status_code=409, detail="Ese tipo de evento ya existe")
        category = Category(name=name, color=payload.color)
        session.add(category)
        session.commit()
        session.refresh(category)
        return {"id": category.id, "name": category.name, "color": category.color}


@app.delete("/api/categories/{category_id}")
def delete_category(category_id: str, _: User = Depends(admin_user)) -> dict:
    with Session(engine) as session:
        category = session.get(Category, category_id)
        if not category:
            raise HTTPException(status_code=404, detail="Tipo de evento no encontrado")
        if category.name == "Otros":
            raise HTTPException(status_code=400, detail="No puedes eliminar el tipo de evento Otros")
        for video in session.scalars(select(Video).where(Video.event_type == category.name)):
            video.event_type = "Otros"
        session.delete(category)
        session.commit()
    return {"ok": True}


@app.get("/api/sources")
def list_sources(_: User = Depends(admin_user)) -> list[dict]:
    return [{"name": p.name, "path": str(p), "connected": p.is_dir()} for p in SOURCES_ROOT.iterdir()]


@app.get("/api/sources/{source_name}")
def browse_source(source_name: str, _: User = Depends(admin_user)) -> list[dict]:
    source = (SOURCES_ROOT / source_name).resolve()
    if SOURCES_ROOT.resolve() not in source.parents or not source.is_dir():
        raise HTTPException(status_code=404, detail="Disco no encontrado")
    return [{"name": p.name, "path": str(p.relative_to(SOURCES_ROOT)), "size": p.stat().st_size, "isVideo": p.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv"}} for p in source.rglob("*") if p.is_file()]


def source_file(path: str) -> Path:
    root = SOURCES_ROOT.resolve()
    candidate = (root / path).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=400, detail="Archivo no válido")
    return candidate


def media_target(filename: str, media_type: str, recorded_on: date) -> Path:
    directory_by_type = {
        "video": "videos",
        "audio": "audios",
        "image": "photos",
        "document": "documents",
        "letter": "documents",
    }
    directory = directory_by_type.get(media_type, "documents")
    target_directory = MEDIA_ROOT / directory / f"{recorded_on.year:04d}" / f"{recorded_on.month:02d}" / f"{recorded_on.day:02d}"
    target_directory.mkdir(parents=True, exist_ok=True, mode=0o775)
    os.chmod(target_directory, 0o775)
    target = target_directory / f"{uuid.uuid4()}_{Path(filename).name}"
    return target


def content_hash(source) -> str:
    source.seek(0)
    digest = hashlib.sha256()
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(chunk)
    source.seek(0)
    return digest.hexdigest()


def content_size(source) -> int:
    source.seek(0, 2)
    size = source.tell()
    source.seek(0)
    return size


def existing_duplicate(session: Session, digest: str, size: int, exclude_id: Optional[str] = None) -> Optional[Video]:
    query = select(Video).where(Video.content_hash == digest)
    if exclude_id:
        query = query.where(Video.id != exclude_id)
    duplicate = session.scalar(query)
    if duplicate:
        return duplicate
    query = select(Video).where(Video.content_hash.is_(None))
    if exclude_id:
        query = query.where(Video.id != exclude_id)
    for video in session.scalars(query):
        target = MEDIA_ROOT / video.filename
        if not target.is_file() or target.stat().st_size != size:
            continue
        with target.open("rb") as source:
            if content_hash(source) == digest:
                video.content_hash = digest
                return video
    return None


def store_uploaded_file(source, filename: str, media_type: str, recorded_on: date) -> str:
    if media_type == "image" and Path(filename).suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        from PIL import Image, ImageOps

        target = media_target(Path(filename).with_suffix(".jpg").name, media_type, recorded_on)
        try:
            with Image.open(source) as image:
                converted = ImageOps.exif_transpose(image).convert("RGB")
                converted.save(target, format="JPEG", quality=92)
        except Exception as error:
            if target.is_file():
                target.unlink()
            raise HTTPException(status_code=400, detail="La foto no es válida o no se puede convertir a JPG") from error
        os.chmod(target, 0o664)
        return str(target.relative_to(MEDIA_ROOT))
    target = media_target(filename, media_type, recorded_on)
    with target.open("wb") as buffer:
        shutil.copyfileobj(source, buffer)
    os.chmod(target, 0o664)
    return str(target.relative_to(MEDIA_ROOT))


def watermark_image(source, target: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

    try:
        with Image.open(source) as original:
            image = ImageOps.exif_transpose(original).convert("RGBA")
            width, height = image.size
            font_size = max(28, min(72, round(width * 0.045)))
            font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            font = ImageFont.truetype(font_path, font_size)
            text = "centro.aguirres.ca"
            draw = ImageDraw.Draw(image)
            left, top, right, bottom = draw.textbbox((0, 0), text, font=font, stroke_width=2)
            margin = max(18, round(width * 0.025))
            position = (width - (right - left) - margin, height - (bottom - top) - margin)
            draw.text(position, text, font=font, fill=(255, 255, 255, 0), stroke_width=max(2, round(font_size / 14)), stroke_fill=(255, 255, 255, 190))
            output = image.convert("RGB") if target.suffix.lower() in {".jpg", ".jpeg"} else image
            if target.suffix.lower() in {".jpg", ".jpeg"}:
                output.save(target, quality=94)
            else:
                output.save(target)
    except (UnidentifiedImageError, OSError):
        source.seek(0)
        with target.open("wb") as buffer:
            shutil.copyfileobj(source, buffer)


def detected_media_type(filename: str, content_type: str = "") -> str:
    extension = Path(filename).suffix.lower()
    if extension in {".mp4", ".avi", ".mov", ".mkv", ".webm", ".mpeg", ".mpg"} or content_type.startswith("video/"):
        return "video"
    if extension in IMAGE_EXTENSIONS or content_type.startswith("image/"):
        return "image"
    if extension in {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"} or content_type.startswith("audio/"):
        return "audio"
    return "document"


@app.get("/api/source-files")
def list_source_files(path: str = "", _: User = Depends(editor_user)) -> dict:
    root = SOURCES_ROOT.resolve()
    if not root.is_dir():
        raise HTTPException(status_code=503, detail="La carpeta de archivos del servidor no está disponible")
    ignored_directories = {"$RECYCLE.BIN", "System Volume Information", "Recovery"}
    current = (root / path).resolve()
    if root not in current.parents and current != root or not current.is_dir():
        raise HTTPException(status_code=400, detail="Carpeta no válida")
    entries = []
    for entry in sorted(current.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        relative_path = str(entry.relative_to(root))
        if entry.name in ignored_directories or entry.name.startswith("."):
            continue
        if entry.is_dir():
            entries.append({"name": entry.name, "path": relative_path, "isFolder": True})
        elif entry.is_file():
            entries.append({
                "name": entry.name,
                "path": relative_path,
                "isFolder": False,
                "size": entry.stat().st_size,
                "modifiedAt": datetime.fromtimestamp(entry.stat().st_mtime).isoformat(),
            })
    return {"path": path, "entries": entries}


@app.post("/api/scripts/add-dollar")
def add_dollar_to_source_files(request: RenameScriptRequest, _: User = Depends(admin_user)) -> dict:
    root = SOURCES_ROOT.resolve()
    if not root.is_dir():
        raise HTTPException(status_code=503, detail="La carpeta de archivos del servidor no está disponible")
    selected = []
    for path in dict.fromkeys(request.paths):
        candidate = (root / path).resolve()
        if root not in candidate.parents and candidate != root:
            raise HTTPException(status_code=400, detail="Ruta no válida")
        if not candidate.exists():
            raise HTTPException(status_code=404, detail=f"No existe: {path}")
        selected.extend(candidate.rglob("*") if candidate.is_dir() else [candidate])
        if candidate.is_dir():
            selected.append(candidate)
    items = sorted({item for item in selected if not item.is_symlink() and (item.is_file() or item.is_dir())}, key=lambda item: str(item))
    operations = []
    targets = set()
    selected_paths = set(items)
    for source in items:
        if source.stem.endswith(" $"):
            continue
        target = source.with_name(f"{source.stem} ${source.suffix}")
        if target in targets or (target.exists() and target not in selected_paths):
            raise HTTPException(status_code=409, detail=f"Ya existe el archivo de destino: {target.name}")
        targets.add(target)
        operations.append((source, target))
    for source, target in sorted(operations, key=lambda operation: len(operation[0].parts), reverse=True):
        source.rename(target)
    return {"renamed": len(operations), "skipped": len(items) - len(operations)}


@app.post("/api/source-files/import")
def import_source_file(
    source_path: list[str] = Form(...),
    title: str = Form(...),
    event_type: str = Form("Otros"),
    recorded_on: date = Form(...),
    start_date: Optional[date] = Form(None),
    end_date: Optional[date] = Form(None),
    people: str = Form(""),
    description: str = Form(""),
    visibility: str = Form("public"),
    allowed_users: str = Form(""),
    media_type: str = Form("video"),
    album_id: str = Form(""),
    user: User = Depends(editor_user),
) -> dict:
    validate_date_range(start_date, end_date)
    candidates = [source_file(path) for path in source_path]
    if len(candidates) > 1 and any(candidate.suffix.lower() not in IMAGE_EXTENSIONS for candidate in candidates):
        raise HTTPException(status_code=400, detail="Los slides múltiples solo admiten archivos de imagen")
    with Session(engine) as session:
        album = session.get(Album, album_id) if album_id else None
        if album_id and not album:
            raise HTTPException(status_code=404, detail="Álbum no encontrado")
        if album and not album.is_long_duration:
            recorded_on = album.recorded_on
            event_type = album.event_type
            start_date = end_date = None
        if len(candidates) > 1:
            slide_group_id = str(uuid.uuid4())
            hashes = []
            for candidate in candidates:
                with candidate.open("rb") as source:
                    digest = content_hash(source)
                duplicate = existing_duplicate(session, digest, candidate.stat().st_size)
                if duplicate:
                    raise HTTPException(status_code=409, detail=f"El archivo '{candidate.name}' ya está subido como '{duplicate.title}'")
                if digest in hashes:
                    raise HTTPException(status_code=409, detail=f"El archivo '{candidate.name}' está repetido en la selección")
                hashes.append(digest)
            for position, candidate in enumerate(candidates, start=1):
                with candidate.open("rb") as source:
                    safe_name = store_uploaded_file(source, candidate.name, "image", recorded_on)
                session.add(Video(title=title, event_type=event_type, recorded_on=recorded_on, start_date=start_date, end_date=end_date, people=people, description=description, filename=safe_name, visibility=visibility if visibility in {"public", "restricted"} else "public", allowed_users=allowed_user_ids(session, allowed_users), media_type="image", album_id=album.id if album else None, created_by=user.id, slide_group_id=slide_group_id, content_hash=hashes[position - 1]))
            session.commit()
            return {"title": title, "slides": len(candidates)}
        candidate = candidates[0]
        with candidate.open("rb") as source:
            media_type = media_type if media_type in {"video", "audio", "image", "document", "letter"} else detected_media_type(candidate.name)
            digest = content_hash(source)
            duplicate = existing_duplicate(session, digest, candidate.stat().st_size)
            if duplicate:
                raise HTTPException(status_code=409, detail=f"El archivo ya está subido como '{duplicate.title}'")
            safe_name = store_uploaded_file(source, candidate.name, media_type, recorded_on)
        video = Video(
            title=title,
            event_type=event_type,
            recorded_on=recorded_on,
            start_date=start_date,
            end_date=end_date,
            people=people,
            description=description,
            filename=safe_name,
            visibility=visibility if visibility in {"public", "restricted"} else "public",
            allowed_users=allowed_user_ids(session, allowed_users),
            media_type=media_type,
            album_id=album_id or None,
            created_by=user.id,
            content_hash=digest,
        )
        session.add(video)
        session.commit()
        session.refresh(video)
        return video_dict(video)


@app.post("/api/sources/{source_name}/import")
def import_from_source(
    source_name: str,
    source_path: str = Form(...),
    title: str = Form(...),
    event_type: str = Form("Otros"),
    recorded_on: date = Form(...),
    people: str = Form(""),
    description: str = Form(""),
    media_type: str = Form("video"),
    _: User = Depends(admin_user),
) -> dict:
    source = (SOURCES_ROOT / source_name).resolve()
    candidate = (source / source_path).resolve()
    if SOURCES_ROOT.resolve() not in source.parents or source != source.parent / source.name:
        raise HTTPException(status_code=404, detail="Disco no encontrado")
    if source not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=400, detail="Archivo no válido")
    with candidate.open("rb") as source_file_handle:
        media_type = media_type if media_type in {"video", "audio", "image", "document", "letter"} else detected_media_type(candidate.name)
        safe_name = store_uploaded_file(source_file_handle, candidate.name, media_type, recorded_on)
    with Session(engine) as session:
        video = Video(title=title, event_type=event_type, recorded_on=recorded_on, people=people, description=description, filename=safe_name, media_type=media_type)
        session.add(video)
        session.commit()
        session.refresh(video)
        return video_dict(video)
