"""Configuration loader and validator for NERV EPUB Manager."""

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CompressionConfig:
    """Image compression settings."""

    target_size_ratio: float = 0.10
    jpeg_quality_min: int = 10
    jpeg_quality_max: int = 85
    max_width: int = 1200
    max_height: int = 1600
    convert_png_to_jpeg: bool = True


@dataclass
class Config:
    """Main application configuration."""

    source_dir: str = ""
    destination_dir: str = ""
    theme: str = "plain"
    compression: CompressionConfig = field(default_factory=CompressionConfig)

    @staticmethod
    def _normalize_wsl_path(path_str: str) -> str:
        """Convert Windows path to WSL path if running on Linux."""
        if sys.platform == "linux" and path_str:
            # Matches 'D:\Folder' or 'D:/Folder'
            match = re.match(r"^([a-zA-Z]):[\\/](.*)$", path_str)
            if match:
                drive = match.group(1).lower()
                rest_of_path = match.group(2).replace("\\", "/")
                return f"/mnt/{drive}/{rest_of_path}"
        return path_str

    @classmethod
    def load(cls, config_path: str) -> "Config":
        """Load configuration from a JSON file."""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Fichier de configuration introuvable : {config_path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        compression_data = data.get("compression", {})
        compression = CompressionConfig(
            target_size_ratio=compression_data.get("target_size_ratio", 0.10),
            jpeg_quality_min=compression_data.get("jpeg_quality_min", 10),
            jpeg_quality_max=compression_data.get("jpeg_quality_max", 85),
            max_width=compression_data.get("max_width", 1200),
            max_height=compression_data.get("max_height", 1600),
            convert_png_to_jpeg=compression_data.get("convert_png_to_jpeg", True),
        )

        # Translate paths for WSL if necessary
        src = cls._normalize_wsl_path(data.get("source_dir", ""))
        dst = cls._normalize_wsl_path(data.get("destination_dir", ""))

        config = cls(
            source_dir=src,
            destination_dir=dst,
            theme=data.get("theme", "plain"),
            compression=compression,
        )

        config.validate()
        return config

    def validate(self):
        """Validate configuration values."""
        if not self.source_dir:
            raise ValueError("source_dir doit être spécifié dans la configuration")
        if not self.destination_dir:
            raise ValueError("destination_dir doit être spécifié dans la configuration")
        if not Path(self.source_dir).exists():
            raise FileNotFoundError(
                f"Dossier source introuvable : {self.source_dir}"
            )
        if self.theme.lower() not in ("nerv", "plain"):
            raise ValueError("Le thème doit être 'nerv' ou 'plain'")

        # Validate compression settings
        c = self.compression
        if not (0.01 <= c.target_size_ratio <= 1.0):
            raise ValueError("target_size_ratio doit être entre 0.01 et 1.0")
        if c.jpeg_quality_min < 1 or c.jpeg_quality_max > 100:
            raise ValueError("La qualité JPEG doit être entre 1 et 100")
        if c.jpeg_quality_min > c.jpeg_quality_max:
            raise ValueError("jpeg_quality_min doit être ≤ jpeg_quality_max")
