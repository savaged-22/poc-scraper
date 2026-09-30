from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "scraper-poc"

    global_concurrency: int = 8

    portal_a_concurrency: int = 2
    portal_b_concurrency: int = 2
    portal_c_concurrency: int = 2
    portal_d_concurrency: int = 2
    portal_e_concurrency: int = 2

    scraper_timeout: int = 15
    max_retries: int = 2
    queue_max_size: int = 1000
    worker_shutdown_timeout: int = 30

    @property
    def portal_limits(self):
        return {
            "blackhatworld": 2,
            "zxpk": 2,
            "portal_a": self.portal_a_concurrency,
            "portal_b": self.portal_b_concurrency,
            "portal_c": self.portal_c_concurrency,
            "portal_d": self.portal_d_concurrency,
            "portal_e": self.portal_e_concurrency,
        }


settings = Settings()

