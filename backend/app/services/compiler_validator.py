"""
Compiler Validator — validates generated project structure.

Deterministic check: no LLM call.
Called by the Compiler after code generation and before writing project.zip.

Validates:
  - Required files are present (main.py, requirements.txt, README.md)
  - File contents are non-empty (> minimum byte threshold)
  - requirements.txt contains minimum required packages
  - main.py contains a FastAPI app definition
  - No placeholder patterns found (TODO, NotImplementedError, stub)

Returns a CompilerValidationResult with:
  - valid: bool
  - missing_files: list of filenames not found
  - empty_files: list of filenames below minimum size
  - warnings: non-blocking issues
  - errors: blocking issues (these cause valid=False)
"""
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Required files (compilation fails if any are absent) ──────────────────────

REQUIRED_FILES = [
    "backend/main.py",
    "requirements.txt",
    "README.md",
]

# ── Optional but expected files ───────────────────────────────────────────────

EXPECTED_FILES = [
    "backend/models.py",
    "backend/routes.py",
    "backend/database.py",
    "frontend/index.html",
]

# ── Minimum content size thresholds (bytes) ───────────────────────────────────

MIN_SIZES = {
    "backend/main.py":    50,
    "backend/routes.py":  80,
    "backend/models.py":  50,
    "requirements.txt":   20,
    "README.md":          30,
    "frontend/index.html": 80,
}

# ── Placeholder patterns that indicate incomplete generation ──────────────────

PLACEHOLDER_PATTERNS = [
    r'\bTODO\b',
    r'\bFIXME\b',
    r'raise\s+NotImplementedError',
    r'pass\s*#\s*stub',
    r'\.\.\.  *#\s*implement',
    r'<YOUR_',
    r'INSERT_HERE',
]

# ── Minimum packages required in requirements.txt ─────────────────────────────

REQUIRED_PACKAGES = ["fastapi", "uvicorn", "sqlalchemy", "pydantic"]


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class CompilerValidationResult:
    valid: bool
    missing_files: list[str] = field(default_factory=list)
    empty_files:   list[str] = field(default_factory=list)
    warnings:      list[str] = field(default_factory=list)
    errors:        list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.valid:
            lines = [f"✓ Compiler validation passed ({len(self.warnings)} warning(s))"]
            for w in self.warnings:
                lines.append(f"  ⚠ {w}")
            return "\n".join(lines)
        lines = [f"✗ Compiler validation failed ({len(self.errors)} error(s))"]
        for e in self.errors:
            lines.append(f"  ✗ {e}")
        for w in self.warnings:
            lines.append(f"  ⚠ {w}")
        return "\n".join(lines)


# ── Validator ────────────────────────────────────────────────────────────────

class CompilerValidator:
    """
    Validates the file map produced by the Compiler before zip creation.
    No LLM call. Pure structural and pattern checking.
    """

    def validate(
        self,
        files: dict[str, str],
        session_id: str,
    ) -> CompilerValidationResult:
        """
        Validate a {filename: content} dict from the Compiler.
        Returns CompilerValidationResult.
        """
        missing_files = []
        empty_files = []
        warnings = []
        errors = []

        # ── 1. Required files present ──────────────────────────────────────────
        for required in REQUIRED_FILES:
            if required not in files:
                missing_files.append(required)
                errors.append(f"Required file missing: {required}")

        # ── 2. Expected files (warnings only) ─────────────────────────────────
        for expected in EXPECTED_FILES:
            if expected not in files:
                warnings.append(f"Expected file not generated: {expected}")

        # ── 3. File content checks ─────────────────────────────────────────────
        for filename, content in files.items():
            # Empty/stub check
            min_size = MIN_SIZES.get(filename, 10)
            if len(content.strip()) < min_size:
                empty_files.append(filename)
                errors.append(
                    f"File too small: {filename} "
                    f"({len(content.strip())} chars, minimum {min_size})"
                )

            # Placeholder patterns
            for pattern in PLACEHOLDER_PATTERNS:
                if re.search(pattern, content, re.IGNORECASE):
                    warnings.append(
                        f"Placeholder pattern '{pattern}' found in {filename}"
                    )
                    break  # one warning per file

        # ── 4. requirements.txt package check ────────────────────────────────
        req_content = files.get("requirements.txt", "")
        if req_content:
            req_lower = req_content.lower()
            for pkg in REQUIRED_PACKAGES:
                if pkg not in req_lower:
                    errors.append(f"Missing required package in requirements.txt: {pkg}")

        # ── 5. main.py FastAPI app check ─────────────────────────────────────
        main_content = files.get("backend/main.py", "")
        if main_content:
            if "FastAPI" not in main_content and "fastapi" not in main_content.lower():
                errors.append("backend/main.py does not appear to define a FastAPI app")
            if "app" not in main_content:
                warnings.append("backend/main.py does not contain an 'app' variable")

        valid = len(errors) == 0

        result = CompilerValidationResult(
            valid=valid,
            missing_files=missing_files,
            empty_files=empty_files,
            warnings=warnings,
            errors=errors,
        )

        if valid:
            logger.info(
                f"[{session_id}] CompilerValidator: PASSED "
                f"({len(files)} files, {len(warnings)} warnings)"
            )
        else:
            logger.error(
                f"[{session_id}] CompilerValidator: FAILED — "
                f"errors={errors}, missing={missing_files}"
            )

        return result
