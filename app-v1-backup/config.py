from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings


load_dotenv()


class Settings(BaseSettings):
    app_name: str = "scraper-poc"

    global_concurrency: int = Field(default=8, ge=1)

    portal_a_concurrency: int = Field(default=2, ge=1)
    portal_b_concurrency: int = Field(default=2, ge=1)
    portal_c_concurrency: int = Field(default=2, ge=1)
    portal_d_concurrency: int = Field(default=2, ge=1)
    portal_e_concurrency: int = Field(default=2, ge=1)

    scraper_timeout: float = Field(default=15.0, gt=0)
    max_retries: int = Field(default=2, ge=0)

    queue_max_size: int = Field(default=1000, ge=1)

    worker_shutdown_timeout: float = Field(default=30.0, gt=0)

    @property
    def portal_limits(self) -> dict[str, int]:
        return {
            "portal_a": self.portal_a_concurrency,
            "portal_b": self.portal_b_concurrency,
            "portal_c": self.portal_c_concurrency,
            "portal_d": self.portal_d_concurrency,
            "portal_e": self.portal_e_concurrency,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()