"""
Compiler — converts PRD + SDD + API Spec into a runnable FastAPI project.

Responsibility:
  - compile_project(session_id, prd, sdd, api_spec) → zip path
  - Uses LLM to generate each file (main.py, routes.py, models.py,
    frontend/index.html, requirements.txt, README.md)
  - Zips result and writes to session directory as project.zip

Does NOT:
  - Modify Marshal
  - Modify pipeline flow
  - Touch session state (read-only file access via FileStore)
"""

import io
import json
import logging
import textwrap
import zipfile
from pathlib import Path

from .file_store import FileStore
from .llm_client import LLMClient
from .compiler_validator import CompilerValidator

logger = logging.getLogger(__name__)

_MAX_TOKENS_CODE = 6000
_TIMEOUT_CODE    = 150.0

# ── Prompt loaded from file ──────────────────────────────────────────────────
# The deterministic compiler contract — see prompts/compiler_system.txt.

_PROMPT_PATH   = Path(__file__).parent.parent / "prompts" / "compiler_system.txt"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8").strip()


class Compiler:
    """
    Generates a runnable FastAPI project from pipeline documents.
    Writes project.zip into the session directory.
    """

    def __init__(self, llm_gateway_url: str, storage_base: str = "/pipeline_outputs"):
        self.llm        = LLMClient(llm_gateway_url)
        self.file_store = FileStore(storage_base)
        self.validator  = CompilerValidator()

    async def compile_project(
        self,
        session_id: str,
        prd:        str,
        sdd:        str,
        api_spec:   str,
    ) -> str:
        """
        Compile PRD + SDD + API Spec into a zip of runnable project files.
        Returns the absolute path to project.zip.
        Raises on LLM or parse error.
        """
        logger.info(f"[{session_id}] Compiler: starting code generation")

        user_prompt = (
            f"## PRODUCT REQUIREMENTS DOCUMENT\n{prd}\n\n"
            f"## SYSTEM DESIGN DOCUMENT\n{sdd}\n\n"
            f"## API SPECIFICATION\n{api_spec}\n\n"
            "Generate the complete runnable project as JSON."
        )

        raw = await self.llm.complete(
            system=_SYSTEM_PROMPT,
            user=user_prompt,
            max_tokens=_MAX_TOKENS_CODE,
            session_id=session_id,
            timeout=_TIMEOUT_CODE,
        )

        logger.info(f"[{session_id}] Compiler: LLM response received ({len(raw)} chars)")

        files = self._parse_response(session_id, raw)

        # ── Validate generated file structure (no LLM, deterministic) ──────────
        validation = self.validator.validate(files, session_id)
        if not validation.valid:
            raise ValueError(
                f"[{session_id}] Generated project failed structural validation: "
                + "; ".join(validation.errors)
            )

        zip_path = self._build_zip(session_id, files)

        logger.info(f"[{session_id}] Compiler: project.zip written to {zip_path}")
        return zip_path

    # ── Private helpers ───────────────────────────────────────────────────────

    def _parse_response(self, session_id: str, raw: str) -> dict[str, str]:
        """
        Parse LLM JSON response into {filename: content} dict.
        Strips markdown fences if present. Raises ValueError on failure.
        """
        text = raw.strip()

        # Strip ```json ... ``` fences if the LLM added them
        if text.startswith("```"):
            lines = text.splitlines()
            # Remove opening fence
            start = 1 if lines[0].startswith("```") else 0
            # Remove closing fence
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            text = "\n".join(lines[start:end]).strip()

        try:
            files = json.loads(text)
        except json.JSONDecodeError as exc:
            # Try to extract the JSON object manually
            brace_start = text.find("{")
            brace_end   = text.rfind("}")
            if brace_start != -1 and brace_end != -1:
                try:
                    files = json.loads(text[brace_start:brace_end + 1])
                except json.JSONDecodeError:
                    raise ValueError(
                        f"[{session_id}] Compiler: could not parse LLM JSON response: {exc}"
                    )
            else:
                raise ValueError(
                    f"[{session_id}] Compiler: LLM response is not JSON: {exc}"
                )

        if not isinstance(files, dict) or not files:
            raise ValueError(f"[{session_id}] Compiler: empty or invalid file map")

        logger.info(f"[{session_id}] Compiler: parsed {len(files)} files: {list(files.keys())}")
        return files

    def _build_zip(self, session_id: str, files: dict[str, str]) -> str:
        """
        Write files into a zip archive inside the session directory.
        Returns the absolute path to project.zip.
        """
        session_dir = self.file_store.ensure_session_dir(session_id)
        zip_path    = session_dir / "project.zip"

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for filename, content in files.items():
                zf.writestr(filename, content)

            # Always include a run script
            run_sh = textwrap.dedent("""\
                #!/usr/bin/env bash
                set -e
                echo "Installing dependencies..."
                pip install -r requirements.txt
                echo ""
                echo "Starting server at http://localhost:8000"
                echo "Open http://localhost:8000 in your browser"
                cd backend
                uvicorn main:app --reload --host 0.0.0.0 --port 8000
            """)
            zf.writestr("run.sh", run_sh)

        zip_path.write_bytes(buf.getvalue())
        return str(zip_path)
