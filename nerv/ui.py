"""
Terminal UIs for EPUB Manager.

- NervUI:  full-screen, htop-style Evangelion/NERV dashboard (rich.live.Live).
- PlainUI: clean, sober, scrollback-friendly UI with no Evangelion references.

Aesthetic references for NervUI live in nerv/dashboard.py — amber circuit
matrix with ticking cell numbers, cyan SYNC chevrons, dual countdown timers,
red alert overlays, Japanese subsystem labels.
"""

from __future__ import annotations

import sys
import time

from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text

from nerv.dashboard import (
    EVA_AMBER,
    EVA_CYAN,
    EVA_DIM,
    EVA_ORANGE,
    EVA_RED,
    EVA_WARM,
    EVA_YELLOW,
    TAGLINE,
    Dashboard,
    DashboardProgress,
    _format_duration,
    _format_size,
)
from nerv.stats import Stats

PHASES_PLAIN: dict[int, str] = {
    1: "INITIALISATION",
    2: "COPIE",
    3: "COMPRESSION",
    4: "RAPPORT",
}


# ── NERV full-screen dashboard ────────────────────────────────────────


class NervUI:
    """Drives the fixed full-screen NERV dashboard via rich.live.Live."""

    def __init__(self, console: Console | None = None):
        if console:
            self.console = console
        else:
            if sys.platform == "win32":
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            self.console = Console(force_terminal=True)
        self.dash = Dashboard()
        self.live: Live | None = None

    # ── Live lifecycle ─────────────────────────────────────────────────

    def _start_live(self):
        if self.live is None:
            self.live = Live(
                self.dash,
                console=self.console,
                screen=True,
                auto_refresh=True,
                refresh_per_second=12,
                transient=False,
            )
            self.live.start()

    def _stop_live(self):
        if self.live is not None:
            self.live.stop()
            self.live = None

    # ── Logger sink (routes log lines into the dashboard) ──────────────

    def log_line(self, line: str):
        self.dash.add_log(line)

    # ── Boot ────────────────────────────────────────────────────────────

    def boot_sequence(self):
        self.dash.boot_time = time.time()
        self.dash.set_phase(0)
        self._start_live()
        time.sleep(2.0)  # let the MAGI units stagger online

    # ── Phases ──────────────────────────────────────────────────────────

    def phase_start(self, phase_num: int, description: str = ""):
        self.dash.set_phase(phase_num)
        if phase_num == 1:
            time.sleep(0.8)  # hold on the config frame

    def phase_complete(self, phase_num: int):
        self.dash.mark_complete(phase_num)
        if self.live is not None:
            time.sleep(0.35)

    # ── Progress ────────────────────────────────────────────────────────

    def create_progress(self, total: int, description: str = "TRANSFER") -> DashboardProgress:
        self.dash.total = total
        self.dash.completed = 0
        return DashboardProgress(self.dash)

    # ── Config display ──────────────────────────────────────────────────

    def show_config(self, source: str, destination: str, target_ratio: float, dry_run: bool):
        self.dash.source = source
        self.dash.destination = destination
        self.dash.target_ratio = target_ratio
        self.dash.dry_run = dry_run
        self.dash.add_log(f"SRC  {source}")
        self.dash.add_log(f"DEST {destination}")
        self.dash.add_log(f"TARGET {target_ratio * 100:.0f}% of original size")

    def show_dry_run_warning(self):
        self.dash.dry_run = True
        self.dash.add_log("DRY-RUN — aucun fichier ne sera modifié")

    # ── Report (printed to scrollback after the live window closes) ────

    def show_report(self, stats: Stats):
        self._stop_live()
        c = self.console
        summary = stats.get_summary()

        c.print()
        c.print(f"  [{EVA_ORANGE}]╔{'═' * 58}╗[/]")
        c.print(
            f"  [{EVA_ORANGE}]║[/]  "
            f"[bold {EVA_AMBER}]MAGI  解析レポート  //  ANALYSIS REPORT[/]"
            f"  [{EVA_ORANGE}]║[/]"
        )
        c.print(f"  [{EVA_ORANGE}]╚{'═' * 58}╝[/]")
        c.print()

        table = Table(
            show_header=True,
            header_style=f"bold {EVA_ORANGE}",
            box=box.MINIMAL_DOUBLE_HEAD,
            border_style=EVA_DIM,
            padding=(0, 2),
            min_width=56,
        )
        table.add_column(f"[{EVA_DIM}]PARAMÈTRE[/]", style=EVA_ORANGE, min_width=26)
        table.add_column(f"[{EVA_DIM}]VALEUR[/]", justify="right", min_width=20)

        table.add_row("ファイル  //  Fichiers copiés", f"[bold {EVA_CYAN}]{summary['files_copied']:>6}[/]")
        table.add_row("圧縮  //  Fichiers compressés", f"[bold {EVA_CYAN}]{summary['files_compressed']:>6}[/]")
        table.add_row("スキップ  //  Ignorés", f"[{EVA_DIM}]{summary['files_skipped']:>6}[/]")

        err_count = summary["files_errored"]
        err_val = (
            f"[bold {EVA_RED}]{err_count:>6}  <<<  ALERT[/]" if err_count > 0
            else f"[{EVA_DIM}]{err_count:>6}[/]"
        )
        table.add_row("エラー  //  Erreurs", err_val)
        table.add_row("", "")
        table.add_row("サイズ前  //  Taille originale", f"[{EVA_WARM}]{_format_size(summary['total_original_size']):>12}[/]")
        table.add_row("サイズ後  //  Taille compressée", f"[{EVA_WARM}]{_format_size(summary['total_compressed_size']):>12}[/]")
        table.add_row(
            "ゲイン  //  Gain total",
            f"[bold {EVA_CYAN}]{_format_size(summary['total_gain_bytes']):>8}  ({summary['total_gain_percent']:.1f}%)[/]",
        )
        table.add_row("", "")
        table.add_row("時間  //  Durée", f"[{EVA_AMBER}]{_format_duration(summary['duration_seconds']):>12}[/]")
        c.print(table)

        if stats.top_gains:
            c.print()
            c.print(f"  [{EVA_ORANGE}]▸[/]  [{EVA_AMBER}]TOP 10[/]  [{EVA_DIM}]//  最大圧縮ゲイン  //  MEILLEURS GAINS[/]")
            c.print(f"  [{EVA_DIM}]{'─' * 58}[/]")
            for i, f in enumerate(stats.top_gains, 1):
                bar = "█" * int(f.gain_percent / 5)
                c.print(
                    f"  [{EVA_DIM}][{i:02d}][/]  "
                    f"[{EVA_WARM}]{f.filename[:34]:<34}[/]  "
                    f"[{EVA_DIM}]{_format_size(f.original_size):>8}[/]"
                    f"  [{EVA_DIM}]►[/]  "
                    f"[{EVA_CYAN}]{_format_size(f.compressed_size):>8}[/]"
                    f"  [{EVA_ORANGE}]{bar:<20}[/]"
                    f"  [bold {EVA_AMBER}]{f.gain_percent:.0f}%[/]"
                )

        if stats.files_errored:
            c.print()
            c.print(f"  [bold {EVA_RED}]⚠  ALERT  //  エラー検出  //  ERREURS DÉTECTÉES[/]")
            c.print(f"  [{EVA_RED}]{'─' * 58}[/]")
            for fname, err in stats.files_errored:
                c.print(f"  [{EVA_RED}]✗  {fname}[/]")
                c.print(f"     [{EVA_DIM}]{err}[/]")
        c.print()

    # ── Shutdown ────────────────────────────────────────────────────────

    def shutdown(self):
        self._stop_live()
        c = self.console
        c.print(f"  [{EVA_DIM}]{'▓' * 60}[/]")
        c.print(
            f"  [{EVA_DIM}]STATUS  >>>[/]  "
            f"[bold {EVA_CYAN}]MISSION COMPLETE  //  任務完了[/]"
        )
        c.print(f"  [{EVA_DIM}]{TAGLINE}[/]")
        c.print(f"  [{EVA_DIM}]{'▓' * 60}[/]")
        c.print()


# ── Plain UI ──────────────────────────────────────────────────────────


class PlainUI:
    """Standard, clean terminal UI — no Evangelion references."""

    def __init__(self, console: Console | None = None):
        if console:
            self.console = console
        else:
            if sys.platform == "win32":
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            self.console = Console(force_terminal=True)
        self._start_time = time.time()

    def boot_sequence(self):
        self.console.print("[bold]EPUB Manager[/]")
        self.console.print("Initialisation...")
        self.console.print()

    def phase_start(self, phase_num: int, description: str = ""):
        phase_name = description or PHASES_PLAIN.get(phase_num, "UNKNOWN")
        self.console.print(f"--- ÉTAPE {phase_num}: {phase_name} ---")

    def phase_complete(self, phase_num: int):
        self.console.print(f"✓ Étape {phase_num} terminée.\n")

    def create_progress(self, total: int, description: str = "Traitement") -> Progress:
        return Progress(
            SpinnerColumn(),
            TextColumn(f"[bold]{description}[/]"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self.console,
            transient=False,
        )

    def show_config(self, source: str, destination: str, target_ratio: float, dry_run: bool):
        self.console.print(f"Source      : {source}")
        self.console.print(f"Destination : {destination}")
        self.console.print(f"Ratio cible : {target_ratio * 100:.0f}%")
        if dry_run:
            self.console.print("[bold yellow]Mode        : SIMULATION (DRY-RUN)[/]")
        self.console.print()

    def show_dry_run_warning(self):
        self.console.print(
            "[bold yellow]Attention: Mode simulation (dry-run) actif. "
            "Aucun fichier ne sera modifié.[/]\n"
        )

    def show_report(self, stats: Stats):
        summary = stats.get_summary()
        self.console.print("[bold]Rapport d'exécution[/]")
        self.console.print(f"Fichiers copiés     : {summary['files_copied']}")
        self.console.print(f"Fichiers compressés : {summary['files_compressed']}")
        self.console.print(f"Fichiers ignorés    : {summary['files_skipped']}")
        self.console.print(f"Erreurs             : {summary['files_errored']}")
        self.console.print(f"Taille originale    : {_format_size(summary['total_original_size'])}")
        self.console.print(f"Taille compressée   : {_format_size(summary['total_compressed_size'])}")
        self.console.print(
            f"Gain total          : {_format_size(summary['total_gain_bytes'])} "
            f"({summary['total_gain_percent']:.1f}%)"
        )
        self.console.print(f"Durée totale        : {_format_duration(summary['duration_seconds'])}\n")

        if stats.top_gains:
            self.console.print("[bold]Top 10 — Meilleurs gains de compression[/]")
            for i, f in enumerate(stats.top_gains, 1):
                self.console.print(
                    f"  {i:>2}. {f.filename}  "
                    f"{_format_size(f.original_size)} → {_format_size(f.compressed_size)}  "
                    f"({f.gain_percent:.0f}%)"
                )
            self.console.print()

        if stats.files_errored:
            self.console.print("[bold red]Erreurs:[/]")
            for fname, err in stats.files_errored:
                self.console.print(f"  - {fname}: {err}")
            self.console.print()

    def shutdown(self):
        elapsed = time.time() - self._start_time
        self.console.print(f"Opération terminée en {_format_duration(elapsed)}.")


def create_ui(theme: str = "plain", console: Console | None = None):
    """Factory — returns the requested UI theme."""
    if theme.lower() == "plain":
        return PlainUI(console)
    return NervUI(console)
