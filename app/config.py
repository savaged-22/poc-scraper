import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "scraper-poc"

    global_concurrency: int = 8
    default_portal_concurrency: int = 2

    # Límites específicos opcionales (sobreescribibles por .env)
    portal_niflheim_concurrency: int = 2
    portal_hard_tm_concurrency: int = 2
    portal_cracked_st_concurrency: int = 2
    portal_blackhatworld_concurrency: int = 2
    portal_zxpk_concurrency: int = 2

    scraper_timeout: int = 30
    max_retries: int = 2
    queue_max_size: int = 1000
    worker_shutdown_timeout: int = 30

    # Configuración de secretos
    secrets_dir: str = "secrets/cookies"

    # Configuración de MongoDB
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "scraper_db"
    mongo_enabled: bool = True

    model_config = {
        "env_file": ".env",
        "extra": "ignore",
    }

    def get_portal_limit(self, portal: str) -> int:
        """
        Obtiene el límite de concurrencia para un portal de manera dinámica.
        Busca en variables de entorno PORTAL_{NOMBRE}_CONCURRENCY o usa el default.
        """
        env_key = f"PORTAL_{portal.upper()}_CONCURRENCY"
        val = os.getenv(env_key)
        if val and val.isdigit():
            return int(val)

        # Atributos predefinidos si existen
        attr_name = f"portal_{portal.lower()}_concurrency"
        if hasattr(self, attr_name):
            return getattr(self, attr_name)

        return self.default_portal_concurrency

    @property
    def portal_limits(self) -> dict[str, int]:
        """
        Diccionario base de límites conocidos para retrocompatibilidad.
        """
        return {
            "niflheim": self.portal_niflheim_concurrency,
            "hard_tm": self.portal_hard_tm_concurrency,
            "cracked_st": self.portal_cracked_st_concurrency,
            "blackhatworld": self.portal_blackhatworld_concurrency,
            "zxpk": self.portal_zxpk_concurrency,
        }


settings = Settings()
