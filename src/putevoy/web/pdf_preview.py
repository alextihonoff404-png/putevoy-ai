"""Конвертация xlsx → pdf через LibreOffice headless.

LibreOffice — внешняя зависимость. Если не установлена, эндпоинт PDF
возвращает понятное сообщение, без падения сервера.

Скачать: https://www.libreoffice.org/download/download-libreoffice/
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Стандартные пути установки LibreOffice
_CANDIDATE_PATHS = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice",
    "/usr/bin/libreoffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
]


@dataclass
class PdfResult:
    pdf_path: Optional[Path] = None
    error: Optional[str] = None


def find_libreoffice() -> Optional[str]:
    """Найти исполняемый файл LibreOffice в стандартных местах."""
    # Сначала проверим PATH
    for cmd in ("soffice", "libreoffice"):
        path = shutil.which(cmd)
        if path:
            return path
    # Затем — стандартные пути
    for p in _CANDIDATE_PATHS:
        if os.path.isfile(p):
            return p
    return None


def xlsx_to_pdf(xlsx_path: Path, output_dir: Path) -> PdfResult:
    """Конвертировать xlsx в pdf через LibreOffice headless.

    Returns:
        PdfResult с pdf_path при успехе или error с описанием проблемы.
    """
    soffice = find_libreoffice()
    if not soffice:
        return PdfResult(error=(
            "LibreOffice не установлен. PDF превью недоступно. "
            "Установите LibreOffice: https://www.libreoffice.org/download/ "
            "(после установки перезапустите сервер). "
            "А пока можно скачать .xlsx и открыть его в Excel/LibreOffice локально."
        ))

    output_dir.mkdir(parents=True, exist_ok=True)
    expected_pdf = output_dir / (xlsx_path.stem + ".pdf")
    if expected_pdf.exists():
        expected_pdf.unlink()

    try:
        result = subprocess.run(
            [
                soffice, "--headless", "--convert-to", "pdf",
                "--outdir", str(output_dir),
                str(xlsx_path),
            ],
            capture_output=True, text=True, timeout=120,
            # На Windows LibreOffice пишет stderr в cp1251, а не UTF-8 —
            # игнорируем недекодируемые байты, чтобы subprocess не падал.
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return PdfResult(error="LibreOffice не уложился в 120 секунд")
    except FileNotFoundError as e:
        return PdfResult(error=f"Не удалось запустить LibreOffice: {e}")

    if result.returncode != 0:
        return PdfResult(error=f"LibreOffice вернул код {result.returncode}: {result.stderr[:300]}")
    if not expected_pdf.exists():
        return PdfResult(error="LibreOffice не создал PDF (неизвестная причина)")
    return PdfResult(pdf_path=expected_pdf)
