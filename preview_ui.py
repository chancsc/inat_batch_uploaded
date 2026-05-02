from __future__ import annotations

import platform
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image as PILImage
from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Label, Static


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


def _render_image(path: Path, width: int = 46) -> Text:
    """Render an image as Rich Text using half-block (▄) characters."""
    img = PILImage.open(path).convert("RGB")
    aspect = img.height / img.width
    # Each character = 2 vertical pixels, terminal chars ~2:1 h:w ratio
    pixel_h = max(2, int(width * aspect))
    if pixel_h % 2:
        pixel_h += 1
    img = img.resize((width, pixel_h), PILImage.LANCZOS)
    px = img.load()
    text = Text(no_wrap=True)
    for row in range(0, pixel_h, 2):
        for col in range(width):
            tr, tg, tb = px[col, row]
            br, bg, bb = px[col, row + 1] if row + 1 < pixel_h else (0, 0, 0)
            text.append(
                "▄",
                Style(
                    color=f"rgb({br},{bg},{bb})",
                    bgcolor=f"rgb({tr},{tg},{tb})",
                ),
            )
        text.append("\n")
    return text


class ImagePanel(Static):
    DEFAULT_CSS = """
    ImagePanel {
        width: 50;
        border: solid $primary-darken-2;
        height: 1fr;
        padding: 0;
        overflow: hidden;
    }
    """

    _cache: dict[Path, Text] = {}

    def show(self, path: Path | None) -> None:
        if path is None or not path.exists():
            self.update("[dim]no image[/dim]")
            return
        if path not in self._cache:
            try:
                self._cache[path] = _render_image(path, width=46)
            except Exception:
                self._cache[path] = Text(f"[error loading {path.name}]")
        self.update(self._cache[path])


class PreviewApp(App):
    CSS = """
    DataTable { height: 1fr; }
    #header-info { padding: 0 1; color: $text-muted; }
    #main-split { height: 1fr; }
    #table-panel { width: 1fr; height: 1fr; }
    """

    BINDINGS = [
        Binding("space", "toggle_row", "Toggle", show=True),
        Binding("a", "select_all", "All", show=True),
        Binding("n", "select_none", "None", show=True),
        Binding("enter", "open_external", "Open externally", show=True),
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
        with Horizontal(id="main-split"):
            with Vertical(id="table-panel"):
                yield DataTable()
            yield ImagePanel(id="image-panel")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_columns("☑", "File", "Date/Time", "Det.", "Species (CV suggestion)", "Notes")
        self._refresh_table()
        # Show first image
        if self.records:
            self._show_image_for(0)

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

    def _show_image_for(self, idx: int) -> None:
        panel = self.query_one(ImagePanel)
        if 0 <= idx < len(self.records):
            cropped = self.records[idx].get("cropped")
            panel.show(Path(cropped) if cropped else None)
        else:
            panel.show(None)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        try:
            idx = int(event.row_key.value)
        except (ValueError, AttributeError):
            return
        self._show_image_for(idx)

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

    def action_open_external(self) -> None:
        idx = self._focused_row_index()
        if idx is not None and 0 <= idx < len(self.records):
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
