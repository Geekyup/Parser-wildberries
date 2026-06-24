from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from .collector import ProductRow
from .config import EXPORT_SCHEMA


def save_excel(rows: list[ProductRow], output_path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "WB Export"
    ws.append([label for _, label in EXPORT_SCHEMA])
    ws.freeze_panes = "A2"

    for cell in ws[1]:
        cell.font = Font(bold=True)

    for row in rows:
        ws.append([row.get(field) for field, _ in EXPORT_SCHEMA])

    for column in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in column)
        ws.column_dimensions[column[0].column_letter].width = min(max_len + 2, 60)

    ws.auto_filter.ref = ws.dimensions
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path
