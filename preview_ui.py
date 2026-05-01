from __future__ import annotations

import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, Label
from textual.containers import Vertical


def _open_image(path: Path) -> None:
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", str(path)])
        elif system == "Windows":
            import os
            os.startfile(str(path))
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


class PreviewApp(App):
    CSS = """
    DataTable { height: 1fr; }
    #header-info { padding: 0 1; color: $text-muted; }
    """

    BINDINGS = [
        Binding("space", "toggle_row", "Toggle", show=True),
        Binding("a", "select_all", "All", show=True),
        Binding("n", "select_none", "None", show=True),
        Binding("enter", "preview_photo", "Preview photo", show=True),
        Binding("u", "upload", "Upload selected", show=True),
        Binding("q", "quit_app", "Quit", show=True),
    ]

    def __init__(self, records: list[dict], location_label: str) -> None:
        super().__init__()
        self.records = records
        self.location_label = location_label
        self.checked: list[bool] = [True] * len(records)
        self.approved_records: list[dict] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(
            f"Trip: {self.location_label}  |  Geoprivacy: obscured",
            id="header-info",
        )
        yield DataTable()
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_columns("☑", "File", "Date/Time", "Det.", "Species (CV suggestion)", "Notes")
        self._refresh_table()

    @staticmethod
    def _format_species(species: dict | None) -> str:
        if not species:
            return "[unknown]"
        parts = []
        if species.get("common_name"):
            parts.append(species["common_name"])
        if species.get("name"):
            parts.append(f'({species["name"]})')
        score = species.get("score", 0.0)
        parts.append(f'cv:{score:.2f}')
        label = " ".join(parts)
        if species.get("low_confidence"):
            return f"{label} ⚠"
        return label

    def _refresh_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        for i, record in enumerate(self.records):
            check = "☑" if self.checked[i] else "☐"
            fname = record["source"].name
            dt: datetime = record["datetime"]
            dt_str = dt.strftime("%Y-%m-%d %H:%M") if dt else "[no datetime]"
            conf = record.get("confidence")
            conf_str = f"{conf:.2f}" if conf is not None else "—"
            species_str = self._format_species(record.get("species"))
            notes = "no detection (full img)" if record.get("fallback") else ""
            table.add_row(check, fname, dt_str, conf_str, species_str, notes, key=str(i))
        self._update_title()

    def _update_title(self) -> None:
        count = sum(self.checked)
        self.title = f"iNat Batch Uploader — {count}/{len(self.records)} selected"

    def _focused_row_index(self) -> int | None:
        table = self.query_one(DataTable)
        if table.cursor_row is None:
            return None
        return table.cursor_row

    def action_toggle_row(self) -> None:
        idx = self._focused_row_index()
        if idx is not None and 0 <= idx < len(self.records):
            self.checked[idx] = not self.checked[idx]
            self._refresh_table()
            table = self.query_one(DataTable)
            table.move_cursor(row=idx)

    def action_select_all(self) -> None:
        self.checked = [True] * len(self.records)
        self._refresh_table()

    def action_select_none(self) -> None:
        self.checked = [False] * len(self.records)
        self._refresh_table()

    def action_preview_photo(self) -> None:
        idx = self._focused_row_index()
        if idx is not None and 0 <= idx < len(self.records):
            cropped = self.records[idx].get("cropped")
            if cropped and Path(cropped).exists():
                _open_image(Path(cropped))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        try:
            idx = int(event.row_key.value)
        except (ValueError, AttributeError):
            return
        cropped = self.records[idx].get("cropped")
        if cropped and Path(cropped).exists():
            _open_image(Path(cropped))

    def action_upload(self) -> None:
        self.approved_records = [r for r, c in zip(self.records, self.checked) if c]
        self.exit()

    def action_quit_app(self) -> None:
        self.approved_records = None
        self.exit()


def run_preview(records: list[dict], location_label: str) -> list[dict] | None:
    app = PreviewApp(records, location_label)
    app.run()
    return app.approved_records
