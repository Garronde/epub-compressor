"""
Full-screen Evangelion/NERV dashboard — a fixed, htop-style live window.

Renders a single frame each refresh from mutable state, so Rich's auto-refresh
animates everything (ticking timers, scrolling circuit grid, SYNC waves) with no
explicit redraw calls. Aesthetic references: the EVA series UI screens —
amber circuit boards with numbered cells, cyan SYNC chevrons, dual countdown
timers, red alert overlays, Japanese subsystem labels.
"""

from __future__ import annotations

import time
from collections import deque

from rich import box
from rich.console import ConsoleOptions, Group, RenderResult
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text

# ── Eva Color Palette ────────────────────────────────────────────────
EVA_ORANGE = "#FF6600"   # primary amber
EVA_AMBER  = "#FFAA22"   # bright amber highlight
EVA_RED    = "#FF1A1A"   # alert red
EVA_CYAN   = "#22FFAA"   # SYNC cyan-green
EVA_PURPLE = "#CC55FF"   # secondary purple
EVA_YELLOW = "#FFEE33"   # warning yellow
EVA_DIM    = "#995522"   # dim amber (pending / decoration)
EVA_DARK   = "#3A2410"   # very dark amber (grid background cells)
EVA_WARM   = "#FFE0B0"   # warm white body text
EVA_GRAY   = "#444444"   # neutral gray

NERV_MARK = r"""███╗   ██╗███████╗██████╗ ██╗   ██╗
████╗  ██║██╔════╝██╔══██╗██║   ██║
██╔██╗ ██║█████╗  ██████╔╝██║   ██║
██║╚██╗██║██╔══╝  ██╔══██╗╚██╗ ██╔╝
██║ ╚████║███████╗██║  ██║ ╚████╔╝
╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝  ╚═══╝  """

PHASES: dict[int, tuple[str, str]] = {
    0: ("システム起動",     "SYSTEM BOOTSTRAP"),
    1: ("初期化",           "INITIALISATION"),
    2: ("データ転送",       "DATA TRANSFER"),
    3: ("パターン・ブルー", "IMAGE COMPRESSION"),
    4: ("解析レポート",     "ANALYSIS REPORT"),
}

TAGLINE = "The fate of destruction is also the joy of rebirth."


# ── Formatting helpers (shared with ui.py) ───────────────────────────


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} o"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} Ko"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} Mo"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} Go"


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s}s"
    else:
        h, rem = divmod(int(seconds), 3600)
        m, s = divmod(rem, 60)
        return f"{h}h {m}m {s}s"


def _hms4(seconds: float) -> str:
    """Format as HH:MM:SS:CC (centiseconds) — the EVA countdown look."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds * 100) % 100)
    return f"{h:02d}:{m:02d}:{s:02d}:{cs:02d}"


# ── Progress shim ─────────────────────────────────────────────────────


class DashboardProgress:
    """
    Drop-in replacement for rich.progress.Progress matching the call pattern
    used by the pipeline:  with p: t = p.add_task(...); p.advance(t)
    Instead of drawing its own bar, it mutates the dashboard state.
    """

    def __init__(self, dash: "Dashboard"):
        self.dash = dash

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.dash.completed = self.dash.total
        return False

    def add_task(self, description: str, total: int | None = None) -> int:
        if total is not None:
            self.dash.total = total
        self.dash.completed = 0
        return 0

    def advance(self, task: int, advance: int = 1):
        self.dash.completed += advance
        if self.dash.phase == 2:
            self.dash.n_copied += advance
        elif self.dash.phase == 3:
            self.dash.n_compressed += advance


# ── Dashboard ─────────────────────────────────────────────────────────


class Dashboard:
    """Mutable state + a fresh full-frame render on every refresh."""

    def __init__(self):
        now = time.time()
        self.start_time = now
        self.boot_time = now

        # config
        self.source = ""
        self.destination = ""
        self.target_ratio = 0.10
        self.dry_run = False

        # phase / progress
        self.phase = 0
        self.op_label = "SYSTEM BOOTSTRAP"
        self.total = 0
        self.completed = 0
        self.completed_phases: set[int] = set()

        # counters
        self.n_copied = 0
        self.n_compressed = 0
        self.n_errors = 0

        # log feed
        self.logs: deque[str] = deque(maxlen=40)

    # ── State mutators (called by NervUI) ────────────────────────────

    def set_phase(self, phase: int):
        self.phase = phase
        jp, en = PHASES.get(phase, ("???", "UNKNOWN"))
        self.op_label = f"{en}  //  {jp}"

    def mark_complete(self, phase: int):
        self.completed_phases.add(phase)

    def add_log(self, line: str):
        self.logs.append(line)
        if "[ERROR" in line or "ERREUR" in line.upper():
            self.n_errors += 1

    # ── Render entrypoint ─────────────────────────────────────────────

    def __rich_console__(self, console, options: ConsoleOptions) -> RenderResult:
        height = options.height or console.height or 40
        width = options.max_width or console.width or 120
        yield self.frame(width, height)

    def frame(self, width: int, height: int) -> Layout:
        root = Layout()
        root.split_column(
            Layout(self._header(width), name="header", size=9),
            Layout(name="mid", ratio=1),
            Layout(self._footer(width), name="footer", size=10),
        )
        mid_h = max(8, height - 19)
        root["mid"].split_row(
            Layout(name="left", size=34),
            Layout(name="center", ratio=1),
        )
        root["mid"]["left"].split_column(
            Layout(self._magi_panel(), name="magi", size=8),
            Layout(self._counters_panel(), name="counters", size=8),
            Layout(self._phases_panel(), name="phases", ratio=1),
        )
        center_inner_w = max(20, width - 34 - 4)
        center_rows = max(3, mid_h - 4)
        root["mid"]["center"].update(self._grid_panel(center_inner_w, center_rows))
        return root

    # ── Animation helpers ─────────────────────────────────────────────

    @property
    def _frame_n(self) -> int:
        return int((time.time() - self.start_time) * 10)

    def _elapsed(self) -> float:
        return time.time() - self.start_time

    def _remaining(self) -> float:
        el = self._elapsed()
        if self.completed <= 0 or self.total <= 0 or el <= 0:
            return 0.0
        rate = self.completed / el
        if rate <= 0:
            return 0.0
        return (self.total - self.completed) / rate

    def _wave(self, n: int, base: str, hi: str, ch: str = "▰") -> Text:
        """A bright band sweeping across `n` cells — SYNC chevron look."""
        band = self._frame_n % max(1, n)
        t = Text()
        for i in range(n):
            if (i - band) % n < 3:
                t.append(ch, style=f"bold {hi}")
            else:
                t.append(ch, style=base)
        return t

    # ── Header ─────────────────────────────────────────────────────────

    def _header(self, width: int) -> Panel:
        grid = Text()
        mark_lines = NERV_MARK.split("\n")

        # Left: NERV mark + title.  Right: dual countdown timers.
        left = Text()
        for ln in mark_lines[:3]:
            left.append("  " + ln + "\n", style=f"bold {EVA_ORANGE}")
        left.append("  N E R V", style=f"bold {EVA_AMBER}")
        left.append("   書庫圧縮システム", style=EVA_DIM)
        left.append("   //   EPUB MANAGEMENT SYSTEM", style=EVA_WARM)

        elapsed = _hms4(self._elapsed())
        remaining = _hms4(self._remaining())
        blink = (self._frame_n // 4) % 2 == 0
        col_el = EVA_AMBER
        col_rm = EVA_CYAN if blink else EVA_DIM

        right = Text(justify="right")
        right.append("第6書庫\n", style=f"bold {EVA_RED}")
        right.append("ELAPSED TIME\n", style=EVA_DIM)
        right.append(elapsed + "\n", style=f"bold {col_el}")
        right.append("EST. REMAINING\n", style=EVA_DIM)
        right.append(remaining, style=f"bold {col_rm}")

        tbl = Layout()
        tbl.split_row(Layout(left, ratio=2), Layout(right, size=20))

        flag = ""
        if self.dry_run:
            flag = "  [DRY-RUN // シミュレーション]" if blink else "  [DRY-RUN]"

        title = Text.assemble(
            ("◢◤ ", EVA_RED),
            ("NERV MAGI SYSTEM", f"bold {EVA_AMBER}"),
            (flag, f"bold {EVA_YELLOW}"),
            (" ◢◤", EVA_RED),
        )
        return Panel(
            tbl,
            title=title,
            title_align="left",
            border_style=EVA_ORANGE,
            box=box.DOUBLE_EDGE,
            padding=0,
        )

    # ── MAGI panel ─────────────────────────────────────────────────────

    def _magi_panel(self) -> Panel:
        units = ["CASPAR", "BALTHASAR", "MELCHIOR"]
        thresholds = [0.4, 0.9, 1.4]
        boot_el = time.time() - self.boot_time

        body = Text()
        for unit, thr in zip(units, thresholds):
            online = self.phase > 0 or boot_el > thr
            if online:
                bar = self._wave(11, EVA_DIM, EVA_CYAN)
                body.append(f"{unit:<10}", style=f"bold {EVA_ORANGE}")
                body.append_text(bar)
                body.append("  SYNC\n", style=f"bold {EVA_CYAN}")
            else:
                body.append(f"{unit:<10}", style=EVA_DIM)
                body.append("░░░░░░░░░░░", style=EVA_DARK)
                body.append("  ....\n", style=EVA_YELLOW)
        body.append("A.T. FIELD ", style=EVA_DIM)
        body.append("NOMINAL", style=f"bold {EVA_CYAN}")

        return Panel(
            body,
            title=Text("MAGI システム", style=f"bold {EVA_CYAN}"),
            title_align="left",
            border_style=EVA_CYAN,
            box=box.HEAVY,
            padding=(0, 1),
        )

    # ── Counters panel ─────────────────────────────────────────────────

    def _counters_panel(self) -> Panel:
        blink = (self._frame_n // 3) % 2 == 0
        body = Text()
        rows = [
            ("COPIÉS",     self.n_copied,     EVA_CYAN),
            ("COMPRESSÉS", self.n_compressed, EVA_CYAN),
        ]
        for label, val, col in rows:
            body.append(f"{label:<12}", style=EVA_DIM)
            body.append(f"{val:0>6}\n", style=f"bold {col}")

        err_col = (EVA_RED if blink else EVA_DIM) if self.n_errors else EVA_DIM
        body.append(f"{'ERREURS':<12}", style=EVA_DIM)
        body.append(f"{self.n_errors:0>6}", style=f"bold {err_col}")
        if self.n_errors and blink:
            body.append("  ⚠ ALERT", style=f"bold {EVA_RED}")

        return Panel(
            body,
            title=Text("カウンタ // COUNTERS", style=f"bold {EVA_AMBER}"),
            title_align="left",
            border_style=EVA_ORANGE,
            box=box.HEAVY,
            padding=(0, 1),
        )

    # ── Phase tracker panel ─────────────────────────────────────────────

    def _phases_panel(self) -> Panel:
        body = Text()
        for n in (1, 2, 3, 4):
            jp, en = PHASES[n]
            if n in self.completed_phases:
                marker, col = "██", EVA_CYAN
                status = "COMPLETE"
            elif n == self.phase:
                blink = (self._frame_n // 3) % 2 == 0
                marker, col = ("▶▶", EVA_YELLOW) if blink else ("▷▷", EVA_AMBER)
                status = "ACTIVE"
            else:
                marker, col = "░░", EVA_DARK
                status = "PENDING"
            body.append(f"{marker} ", style=f"bold {col}")
            body.append(f"0{n}", style=EVA_DIM)
            body.append(f" {en:<18}", style=col if status != "PENDING" else EVA_DIM)
            body.append(f"{status}\n", style=col)
        body.append("\n")
        body.append(TAGLINE, style=EVA_DIM)

        return Panel(
            body,
            title=Text("作戦フェーズ // PHASES", style=f"bold {EVA_AMBER}"),
            title_align="left",
            border_style=EVA_ORANGE,
            box=box.HEAVY,
            padding=(0, 1),
        )

    # ── Center circuit grid ──────────────────────────────────────────────

    def _grid_panel(self, inner_w: int, rows: int) -> Panel:
        cell_w = 8  # "[0042] "
        cols = max(1, inner_w // cell_w)
        capacity = cols * rows
        total = max(self.total, 1)
        completed = self.completed
        frame = self._frame_n

        # Scroll the window so the active cell stays mid-screen.
        start = max(0, min(completed - capacity // 2, max(0, total - capacity)))

        body = Text()
        for r in range(rows):
            for cnum in range(cols):
                idx = start + r * cols + cnum
                if idx >= total:
                    body.append(" " * cell_w)
                    continue
                label = f"[{idx:04d}]"
                if idx < completed:
                    body.append(label + " ", style=EVA_CYAN)            # done
                elif idx == completed:
                    blink = (frame // 1) % 2 == 0
                    style = f"bold {EVA_YELLOW}" if blink else f"bold {EVA_AMBER}"
                    body.append(label + " ", style=style)               # active
                elif idx < completed + cols:
                    body.append(label + " ", style=EVA_ORANGE)          # queued
                else:
                    body.append(label + " ", style=EVA_DARK)            # pending
            body.append("\n")

        pct = (completed / total) * 100 if total else 0.0
        title = Text.assemble(
            ("回路図 // PROCESS MATRIX   ", f"bold {EVA_AMBER}"),
            (f"{completed:0>5}/{total:0>5}   ", EVA_DIM),
            (f"{pct:5.1f}%", f"bold {EVA_CYAN}"),
        )
        border = EVA_RED if self.n_errors else EVA_ORANGE
        return Panel(
            body,
            title=title,
            title_align="left",
            border_style=border,
            box=box.HEAVY,
            padding=(0, 1),
        )

    # ── Footer (op + progress bar + log tail) ────────────────────────────

    def _footer(self, width: int) -> Panel:
        inner = max(20, width - 6)
        total = max(self.total, 1)
        pct = (self.completed / total) if total else 0.0
        frame = self._frame_n

        # Big chevron progress bar
        bar_w = inner
        filled = int(pct * bar_w)
        bar = Text()
        for i in range(bar_w):
            if i < filled:
                # leading-edge shimmer
                if filled - i <= 2 and (frame % 2 == 0):
                    bar.append("█", style=f"bold {EVA_YELLOW}")
                else:
                    bar.append("█", style=EVA_AMBER)
            elif i == filled:
                bar.append("▓", style=f"bold {EVA_YELLOW}")
            else:
                bar.append("─", style=EVA_DARK)

        op = Text.assemble(
            ("▶ ", EVA_RED),
            (self.op_label, f"bold {EVA_ORANGE}"),
            ("    ", ""),
            (f"{pct * 100:5.1f}%", f"bold {EVA_CYAN}"),
            ("   ", ""),
            (f"{self.completed}/{self.total}", EVA_DIM),
        )

        # Log tail
        log_lines = list(self.logs)[-4:]
        logs = Text()
        for ln in log_lines:
            style = EVA_RED if ("ERROR" in ln or "ERREUR" in ln.upper()) else EVA_WARM
            clipped = ln if len(ln) <= inner else ln[: inner - 1] + "…"
            logs.append(clipped + "\n", style=style)

        group = Group(op, bar, Text("", end=""), logs)
        border = EVA_RED if self.n_errors else EVA_ORANGE
        return Panel(
            group,
            title=Text("作戦状況 // OPERATION STATUS", style=f"bold {EVA_AMBER}"),
            title_align="left",
            border_style=border,
            box=box.DOUBLE_EDGE,
            padding=(0, 1),
        )
