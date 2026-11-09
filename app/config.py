"""Configuración central del sistema.

Todos los valores salen de variables de entorno (archivo .env en local o
`env_file` en Docker Compose). Ningún secreto se escribe en el código.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # En Docker las variables ya vienen cargadas; en local leemos .env
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

BASE_DIR = Path(__file__).resolve().parent.parent


def _lista(valor: str) -> list[str]:
    return [v.strip().lower() for v in valor.split(",") if v.strip()]


@dataclass
class Config:
    # --- Persistencia ---
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", BASE_DIR / "data")))

    # --- IA: orden de proveedores para el fallback ---
    ia_proveedores: list[str] = field(
        default_factory=lambda: _lista(os.getenv("IA_PROVEEDORES", "gemini,groq,ollama"))
    )
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-flash-latest"))
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    groq_model: str = field(default_factory=lambda: os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"))
    ollama_url: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.2"))
    ia_timeout: float = field(default_factory=lambda: float(os.getenv("IA_TIMEOUT", "60")))

    # --- Telegram ---
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_bot_username: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_USERNAME", ""))
    telegram_channel_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHANNEL_ID", ""))

    # --- n8n (para que la API dispare el workflow de entrega) ---
    n8n_webhook_entrega: str = field(
        default_factory=lambda: os.getenv("N8N_WEBHOOK_ENTREGA", "http://localhost:5678/webhook/entrega")
    )

    # --- Negocio ---
    precio_por_defecto: float = field(default_factory=lambda: float(os.getenv("PRECIO_POR_DEFECTO", "0")))
    alias_transferencia: str = field(
        default_factory=lambda: os.getenv("ALIAS_TRANSFERENCIA", "cuentos.ia.demo (dato ficticio)")
    )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "tienda.db"

    @property
    def cuentos_dir(self) -> Path:
        return self.data_dir / "cuentos"


config = Config()