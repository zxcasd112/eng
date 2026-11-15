import ipaddress
import logging
import re
import socket
import urllib.parse
from html.parser import HTMLParser

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import SavedText, User
from app.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/sources", tags=["sources"])

MAX_CONTENT_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB
FETCH_TIMEOUT_SECONDS = 10.0


class URLIngestRequest(BaseModel):
    url: str = Field(..., description="Public HTTP/HTTPS URL of the article")


class TextIngestRequest(BaseModel):
    title: str = Field(default="Пользовательский текст", max_length=255)
    text: str = Field(..., min_length=10, max_length=50000)
    topic: str = Field(default="Custom Text", max_length=128)
    cefr_level: str | None = None


class IngestResponse(BaseModel):
    id: int
    title: str
    body: str
    cefr_level: str
    topic: str
    source_type: str
    url_or_ref: str | None = None


class SimpleHTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.in_title = False
        self.in_ignored = False
        self.ignored_tags = {"script", "style", "nav", "header", "footer", "aside", "noscript", "svg", "form"}
        self.paragraphs = []
        self.current_para = []

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        if tag_lower in self.ignored_tags:
            self.in_ignored = True
        elif tag_lower == "title":
            self.in_title = True
        elif tag_lower in ("p", "div", "h1", "h2", "h3", "h4", "article", "section") and self.current_para:
            text = "".join(self.current_para).strip()
            if text:
                self.paragraphs.append(text)
            self.current_para = []

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if tag_lower in self.ignored_tags:
            self.in_ignored = False
        elif tag_lower == "title":
            self.in_title = False
        elif tag_lower in ("p", "div", "h1", "h2", "h3", "h4", "article", "section") and self.current_para:
            text = "".join(self.current_para).strip()
            if text:
                self.paragraphs.append(text)
            self.current_para = []

    def handle_data(self, data):
        if self.in_ignored:
            return
        if self.in_title:
            self.title += data
        else:
            self.current_para.append(data)

    def get_clean_text(self) -> tuple[str, str]:
        if self.current_para:
            text = "".join(self.current_para).strip()
            if text:
                self.paragraphs.append(text)

        meaningful_paras = [
            re.sub(r"\s+", " ", p).strip()
            for p in self.paragraphs
            if len(re.findall(r"\b[A-Za-z'-]+\b", p)) >= 4
        ]
        body = "\n\n".join(meaningful_paras)
        title = re.sub(r"\s+", " ", self.title).strip()
        return title, body


def validate_url_and_check_ssrf(url_str: str) -> str:
    parsed = urllib.parse.urlparse(url_str)
    if parsed.scheme.lower() not in ("http", "https"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Поддерживаются только URL с протоколами http:// и https://",
        )

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Некорректный адрес URL (отсутствует имя хоста)",
        )

    # Check loopback string names
    if hostname.lower() in ("localhost", "ip6-localhost", "ip6-loopback", "local"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Запросы к локальным адресам запрещены (SSRF protection)",
        )

    # Resolve IP addresses
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Не удалось разрешить адрес хоста: {hostname}",
        ) from exc

    for addr in addr_info:
        ip_str = addr[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Запросы к приватным и локальным IP-адресам запрещены (SSRF protection)",
                )
        except ValueError:
            continue

    return url_str


@router.post("/url", response_model=IngestResponse)
async def ingest_url(
    payload: URLIngestRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> IngestResponse:
    validated_url = validate_url_and_check_ssrf(payload.url)

    # Download article with SSRF and size guard
    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True) as client:
            resp = await client.get(validated_url)
            # Verify final redirected URL for SSRF as well
            validate_url_and_check_ssrf(str(resp.url))

            content_type = resp.headers.get("content-type", "").lower()
            if not any(t in content_type for t in ("text/html", "text/plain", "application/xhtml+xml")):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Неподдерживаемый тип содержимого: {content_type}. Ожидался text/html или text/plain.",
                )

            if len(resp.content) > MAX_CONTENT_SIZE_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Размер страницы превышает допустимый лимит (2 МБ)",
                )

            raw_text = resp.text
    except HTTPException:
        raise
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Время ожидания ответа от сервера истекло (таймаут 10 с)",
        ) from exc
    except Exception as exc:
        logger.warning("Failed to fetch article from url=%s: %s", payload.url, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Не удалось загрузить страницу: {exc}",
        ) from exc

    # Parse and extract readable text
    if "text/plain" in content_type:
        title = urllib.parse.urlparse(validated_url).path.split("/")[-1] or "Текстовая статья"
        body = raw_text.strip()
    else:
        parser = SimpleHTMLTextExtractor()
        parser.feed(raw_text)
        title, body = parser.get_clean_text()
        if not title:
            title = urllib.parse.urlparse(validated_url).hostname or "Web Article"

    if len(body) < 30:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="На странице не найдено достаточно связного текста для чтения.",
        )

    saved_text = SavedText(
        user_id=user.id,
        title=title[:250],
        body=body,
        cefr_level=user.cefr_level or "B1",
        topic="Web Article",
        source_type="url",
        url_or_ref=validated_url,
    )
    session.add(saved_text)
    await session.commit()
    await session.refresh(saved_text)

    return IngestResponse(
        id=saved_text.id,
        title=saved_text.title,
        body=saved_text.body,
        cefr_level=saved_text.cefr_level,
        topic=saved_text.topic,
        source_type=saved_text.source_type,
        url_or_ref=saved_text.url_or_ref,
    )


@router.post("/text", response_model=IngestResponse)
async def ingest_text(
    payload: TextIngestRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> IngestResponse:
    saved_text = SavedText(
        user_id=user.id,
        title=payload.title.strip()[:250],
        body=payload.text.strip(),
        cefr_level=(payload.cefr_level or user.cefr_level or "B1").upper(),
        topic=payload.topic.strip()[:120],
        source_type="custom",
    )
    session.add(saved_text)
    await session.commit()
    await session.refresh(saved_text)

    return IngestResponse(
        id=saved_text.id,
        title=saved_text.title,
        body=saved_text.body,
        cefr_level=saved_text.cefr_level,
        topic=saved_text.topic,
        source_type=saved_text.source_type,
        url_or_ref=None,
    )
