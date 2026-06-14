"""Statistics collector and reporter for NERV EPUB Manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import time


@dataclass
class FileStats:
    """Compression statistics for a single file."""

    filename: str
    original_size: int
    compressed_size: int

    @property
    def gain_bytes(self) -> int:
        """Absolute size reduction in bytes."""
        return self.original_size - self.compressed_size

    @property
    def gain_percent(self) -> float:
        """Percentage of size reduction (0-100)."""
        if self.original_size == 0:
            return 0.0
        return (1 - self.compressed_size / self.original_size) * 100


@dataclass
class Stats:
    """
    Aggregates all pipeline statistics.

    Tracks copied files, compressed files, skipped files, errors,
    and timing information for the final MAGI report.
    """

    files_compressed: list[FileStats] = field(default_factory=list)
    files_copied: list[tuple[str, int]] = field(default_factory=list)
    files_skipped: list[tuple[str, str]] = field(default_factory=list)
    files_errored: list[tuple[str, str]] = field(default_factory=list)
    start_time: float = field(default_factory=time)
    end_time: float | None = None

    def add_compressed(self, filename: str, original_size: int, compressed_size: int):
        """Record a successfully compressed file."""
        self.files_compressed.append(FileStats(filename, original_size, compressed_size))

    def add_copied(self, filename: str, size: int):
        """Record a successfully copied file."""
        self.files_copied.append((filename, size))

    def add_skipped(self, filename: str, reason: str):
        """Record a skipped file with reason."""
        self.files_skipped.append((filename, reason))

    def add_error(self, filename: str, error: str):
        """Record a file that failed processing."""
        self.files_errored.append((filename, error))

    def finish(self):
        """Mark the end of the pipeline."""
        self.end_time = time()

    @property
    def duration_seconds(self) -> float:
        """Total elapsed time in seconds."""
        end = self.end_time or time()
        return end - self.start_time

    @property
    def total_original_size(self) -> int:
        """Sum of all original file sizes (compressed files only)."""
        return sum(f.original_size for f in self.files_compressed)

    @property
    def total_compressed_size(self) -> int:
        """Sum of all compressed file sizes."""
        return sum(f.compressed_size for f in self.files_compressed)

    @property
    def total_gain_bytes(self) -> int:
        """Total bytes saved by compression."""
        return self.total_original_size - self.total_compressed_size

    @property
    def total_gain_percent(self) -> float:
        """Overall compression gain as percentage."""
        if self.total_original_size == 0:
            return 0.0
        return (1 - self.total_compressed_size / self.total_original_size) * 100

    @property
    def top_gains(self) -> list[FileStats]:
        """Top 10 files with the largest compression gains."""
        return sorted(
            self.files_compressed, key=lambda f: f.gain_bytes, reverse=True
        )[:10]

    def get_summary(self) -> dict:
        """Return a dict of all summary metrics for reporting."""
        return {
            "files_compressed": len(self.files_compressed),
            "files_copied": len(self.files_copied),
            "files_skipped": len(self.files_skipped),
            "files_errored": len(self.files_errored),
            "total_original_size": self.total_original_size,
            "total_compressed_size": self.total_compressed_size,
            "total_gain_bytes": self.total_gain_bytes,
            "total_gain_percent": self.total_gain_percent,
            "duration_seconds": self.duration_seconds,
        }
