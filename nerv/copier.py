"""EPUB file copier — recursive copy preserving directory structure."""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

from nerv.config import Config
from nerv.logger import NervLogger
from nerv.stats import Stats


def find_epubs(source_dir: str) -> list[Path]:
    """
    Recursively find all .epub files under source_dir.

    Returns sorted list of absolute Path objects.
    """
    source = Path(source_dir)
    return sorted(source.rglob("*.epub"))


def get_epub_metadata(epub_path: Path) -> tuple[str | None, str | None]:
    """
    Extract title and author from an EPUB file.
    Uses regex to avoid XML namespace issues.
    """
    try:
        with zipfile.ZipFile(epub_path, "r") as z:
            # First, find the OPF file from container.xml
            try:
                container_data = z.read("META-INF/container.xml").decode("utf-8")
                match = re.search(r'full-path="([^"]+)"', container_data)
                if not match:
                    return None, None
                opf_path = match.group(1)
            except KeyError:
                # If no container.xml, try looking for any .opf file
                opf_files = [f for f in z.namelist() if f.endswith(".opf")]
                if not opf_files:
                    return None, None
                opf_path = opf_files[0]

            # Read OPF and extract metadata
            opf_data = z.read(opf_path).decode("utf-8", errors="ignore")
            
            title_match = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", opf_data, re.IGNORECASE | re.DOTALL)
            author_match = re.search(r"<dc:creator[^>]*>(.*?)</dc:creator>", opf_data, re.IGNORECASE | re.DOTALL)
            
            title = title_match.group(1).strip() if title_match else None
            author = author_match.group(1).strip() if author_match else None
            
            # Clean up HTML entities or tags if any slipped in
            if title:
                title = re.sub(r"<[^>]+>", "", title)
            if author:
                author = re.sub(r"<[^>]+>", "", author)
                
            return title, author
    except Exception:
        return None, None


def _clean_filename(name: str) -> str:
    """Remove invalid characters for Windows filenames."""
    # Replace invalid chars with underscore or space
    clean = re.sub(r'[<>:"/\\|?*]', '_', name)
    # Remove control characters
    clean = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', clean)
    return clean.strip()


def copy_epubs(
    config: Config,
    logger: NervLogger,
    stats: Stats,
    dry_run: bool = False,
    progress_callback: callable | None = None,
) -> list[str]:
    """
    Copy all EPUBs from source to destination, flattening the directory
    structure and renaming files to "Author - Title.epub".

    Args:
        config: Application configuration.
        logger: NERV logger instance.
        stats: Statistics collector.
        dry_run: If True, simulate without writing.
        progress_callback: Called after each file (for progress bar).

    Returns:
        List of absolute paths to copied files in destination.
    """
    source = Path(config.source_dir)
    destination = Path(config.destination_dir)
    epub_files = find_epubs(config.source_dir)

    if not epub_files:
        logger.warning("Aucun fichier EPUB trouvé dans le dossier source")
        return []

    logger.info(f"{len(epub_files)} fichiers EPUB détectés dans {source}")
    copied_files: list[str] = []

    for epub_path in epub_files:
        # ── Determine new filename ──
        title, author = get_epub_metadata(epub_path)
        
        if title and author:
            new_name = f"{_clean_filename(author)} - {_clean_filename(title)}.epub"
        elif title:
            new_name = f"{_clean_filename(title)}.epub"
        else:
            new_name = epub_path.name
            
        dest_path = destination / new_name

        # ── Handle collisions ──
        # Overwrite files from previous runs (same name = same book).
        # But if two source books map to the same output name in THIS run, append a counter.
        counter = 1
        original_dest_path = dest_path
        while str(dest_path) in copied_files:
            dest_path = destination / f"{original_dest_path.stem}_{counter}.epub"
            counter += 1

        try:
            file_size = epub_path.stat().st_size

            if dry_run:
                logger.debug(f"[DRY-RUN] Copierait : {epub_path.name} → {dest_path.name}")
                stats.add_copied(dest_path.name, file_size)
                copied_files.append(str(dest_path))
            else:
                # Ensure destination directory exists
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copy2(epub_path, dest_path)
                copied_size = dest_path.stat().st_size
                stats.add_copied(dest_path.name, copied_size)
                copied_files.append(str(dest_path))
                logger.debug(f"Copié : {epub_path.name} → {dest_path.name}")

        except Exception as e:
            logger.error(f"Erreur copie {epub_path.name} : {e}")
            stats.add_error(epub_path.name, str(e))

        if progress_callback:
            progress_callback()

    logger.info(f"{len(copied_files)} fichiers copiés vers {destination}")
    return copied_files
