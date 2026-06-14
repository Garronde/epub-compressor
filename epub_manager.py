#!/usr/bin/env python3
"""
NERV EPUB Manager — Copy and compress EPUB files with Evangelion-themed UI.

Usage examples:
    python epub_manager.py                     # Full pipeline: copy → compress
    python epub_manager.py --dry-run           # Simulation (no files modified)
    python epub_manager.py --copy-only         # Copy only, no compression
    python epub_manager.py --compress-only     # Compress destination folder only
    python epub_manager.py --config other.json # Use a different config file
    python epub_manager.py --verbose           # Show debug logs in terminal
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from nerv.compressor import compress_epubs
from nerv.config import Config
from nerv.copier import copy_epubs, find_epubs
from nerv.logger import NervLogger
from nerv.stats import Stats
from nerv.ui import create_ui


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="NERV EPUB Manager — Copie et compression d'EPUBs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemples :\n"
            "  python epub_manager.py                  Pipeline complet\n"
            "  python epub_manager.py --dry-run         Simulation\n"
            "  python epub_manager.py --compress-only   Compresser la destination\n"
        ),
    )
    parser.add_argument(
        "--config",
        "-c",
        default="config.json",
        help="Chemin vers le fichier de configuration (défaut : config.json)",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Mode simulation — aucun fichier ne sera modifié",
    )
    parser.add_argument(
        "--copy-only",
        action="store_true",
        help="Copier les fichiers sans les compresser",
    )
    parser.add_argument(
        "--compress-only",
        action="store_true",
        help="Compresser les fichiers du dossier destination (sans copie)",
    )
    parser.add_argument(
        "--theme",
        "-t",
        choices=["nerv", "plain"],
        help="Thème de l'interface (nerv ou plain). Remplace celui de la config.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Afficher les logs détaillés (DEBUG) dans le terminal",
    )
    return parser.parse_args()


def main():
    """Main entry point — orchestrates the copy → compress pipeline."""
    args = parse_args()

    # ── Load configuration ──────────────────────────────────────────
    try:
        config = Config.load(args.config)
    except (FileNotFoundError, ValueError, Exception) as e:
        print(f"\n  ERREUR CRITIQUE : {e}\n")
        sys.exit(1)

    # ── Initialize UI ───────────────────────────────────────────────
    theme_choice = args.theme if args.theme else config.theme
    ui = create_ui(theme_choice)

    # ── Boot ────────────────────────────────────────────────────────
    ui.boot_sequence()

    # ── Initialize logger & stats ───────────────────────────────────
    # In the NERV theme, route log lines into the dashboard's log feed so they
    # don't corrupt the full-screen live window.
    logger = NervLogger(verbose=args.verbose, sink=getattr(ui, "log_line", None))
    stats = Stats()

    logger.info("═" * 50)
    logger.info("EPUB Manager — Démarrage")
    logger.info(f"Configuration : {args.config}")

    # ── Phase 1: Initialisation ─────────────────────────────────────
    ui.phase_start(1)
    ui.show_config(
        config.source_dir,
        config.destination_dir,
        config.compression.target_size_ratio,
        args.dry_run,
    )
    if args.dry_run:
        ui.show_dry_run_warning()
        
    # Delete .caltrash if it exists in the source directory
    caltrash_path = Path(config.source_dir) / ".caltrash"
    if caltrash_path.exists() and caltrash_path.is_dir():
        if args.dry_run:
            logger.debug(f"[DRY-RUN] Supprimerait le dossier : {caltrash_path}")
        else:
            logger.info(f"Suppression du dossier {caltrash_path}")
            try:
                shutil.rmtree(caltrash_path)
            except Exception as e:
                logger.error(f"Impossible de supprimer {caltrash_path} : {e}")

    ui.phase_complete(1)

    # ── Phase 2: Copy ───────────────────────────────────────────────
    copied_files: list[str] = []

    if not args.compress_only:
        ui.phase_start(2)

        epub_files = find_epubs(config.source_dir)
        if epub_files:
            progress = ui.create_progress(len(epub_files), "Copie")
            with progress:
                task = progress.add_task("copy", total=len(epub_files))
                copied_files = copy_epubs(
                    config,
                    logger,
                    stats,
                    dry_run=args.dry_run,
                    progress_callback=lambda: progress.advance(task),
                )
        else:
            logger.warning("Aucun fichier EPUB trouvé dans le dossier source.")

        ui.phase_complete(2)

    # ── Phase 3: Compress ───────────────────────────────────────────
    if not args.copy_only:
        ui.phase_start(3)

        if args.compress_only:
            # Compress files already in destination
            dest_epubs = find_epubs(config.destination_dir)
            files_to_compress = [str(p) for p in dest_epubs]
        else:
            files_to_compress = copied_files

        if files_to_compress:
            progress = ui.create_progress(len(files_to_compress), "Compression")
            with progress:
                task = progress.add_task("compress", total=len(files_to_compress))
                compress_epubs(
                    files_to_compress,
                    config,
                    logger,
                    stats,
                    dry_run=args.dry_run,
                    progress_callback=lambda: progress.advance(task),
                )
        else:
            logger.warning("Aucun fichier à compresser.")

        ui.phase_complete(3)

    # ── Phase 4: MAGI Report ────────────────────────────────────────
    ui.phase_start(4)
    stats.finish()
    ui.show_report(stats)
    ui.phase_complete(4)

    # ── Shutdown ────────────────────────────────────────────────────
    logger.info(f"Terminé — {stats.get_summary()}")
    logger.info("═" * 50)
    ui.shutdown()


if __name__ == "__main__":
    main()
