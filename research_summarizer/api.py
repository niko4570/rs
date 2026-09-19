"""Minimal local FastAPI layer for the Research Summarizer Agent.

Thin adapter between HTTP and the existing Agent core (``run_agent``).
The CLI and this API reuse the same application logic.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from openai import APIError
from starlette.concurrency import run_in_threadpool

from research_summarizer.agent import run_agent
from research_summarizer.evidence import PROJECT_ROOT
from research_summarizer.models import SummaryResult
from research_summarizer.parser import ParseError

# Uploaded files are stored under the project root so the existing
# ``read_text_file`` tool (which refuses paths outside the project root)
# can read them without weakening that security boundary.
_UPLOADS_DIR = PROJECT_ROOT / ".uploads"
_UPLOADS_RELATIVE_DIR = ".uploads"

_ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown"}
_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB

app = FastAPI(title="Research Summarizer API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness check used by the frontend and local tooling."""
    return {"status": "ok"}


@app.post("/api/research", response_model=SummaryResult)
async def research(
    input_type: Annotated[str, Form()],
    url: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
) -> SummaryResult:
    """Run the research workflow for a URL or an uploaded text file.

    The request is converted into the single free-form string that
    ``run_agent`` already accepts, so the API does not duplicate the
    workflow.
    """
    request = await _build_request(input_type, url, file)
    return await run_in_threadpool(_execute, request)


def _execute(request: str) -> SummaryResult:
    """Call the Agent core and translate known failures into HTTP errors."""
    try:
        return run_agent(request)
    except ParseError as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not produce a valid structured result.",
        ) from exc
    except ValueError as exc:
        if "Missing API configuration" in str(exc):
            raise HTTPException(
                status_code=503,
                detail=(
                    "Agent is not configured. Set OPENAI_API_KEY, "
                    "OPENAI_BASE_URL, and OPENAI_MODEL."
                ),
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="Agent planning failed.",
        ) from exc
    except APIError as exc:
        raise HTTPException(
            status_code=502,
            detail="LLM provider error.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unexpected internal error.",
        ) from exc


async def _build_request(
    input_type: str,
    url: str | None,
    file: UploadFile | None,
) -> str:
    """Validate the request and return the free-form agent input string."""
    if input_type == "url":
        return _validate_url(url)
    if input_type == "file":
        return await _save_upload(file)
    raise HTTPException(
        status_code=400,
        detail="input_type must be 'url' or 'file'.",
    )


def _validate_url(url: str | None) -> str:
    """Return a validated http(s) URL or raise a client error."""
    if not url or not url.strip():
        raise HTTPException(
            status_code=400,
            detail="A URL is required when input_type is 'url'.",
        )

    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=400,
            detail="Invalid URL. Only http:// and https:// URLs are supported.",
        )
    return url


async def _save_upload(file: UploadFile | None) -> str:
    """Validate an uploaded text file, persist it, and return the agent input.

    The file is saved under the project root (with a generated name) so the
    agent's existing ``read_text_file`` tool can read it via a relative path.
    """
    if file is None:
        raise HTTPException(
            status_code=400,
            detail="A file is required when input_type is 'file'.",
        )

    filename = file.filename or ""
    extension = Path(filename).suffix.lower()
    if extension not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{extension or 'unknown'}'. "
                "Only .txt and .md files are supported."
            ),
        )

    content = await file.read()
    if len(content) > _MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="File is too large (max 10 MB).",
        )

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="File must be valid UTF-8 text.",
        ) from exc

    if not text.strip():
        raise HTTPException(
            status_code=400,
            detail="File is empty.",
        )

    _UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}{extension}"
    (_UPLOADS_DIR / safe_name).write_bytes(content)

    return f"Summarize the local file: {_UPLOADS_RELATIVE_DIR}/{safe_name}"
