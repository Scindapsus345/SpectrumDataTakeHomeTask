from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from page_crawler.crawler import CrawlerSettings
from page_crawler.page_fetcher import PageFetcherSettings


class WebServerSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = Field(8000, ge=1, le=65535)


class PostgresSettings(BaseModel):
    dsn: str = "postgresql://crawler:crawler@127.0.0.1:5432/crawler"


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PAGE_CRAWLER_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    log_level: str = "INFO"
    web_server: WebServerSettings = WebServerSettings()
    postgres: PostgresSettings = PostgresSettings()
    crawler: CrawlerSettings = CrawlerSettings()
    page_fetcher: PageFetcherSettings = PageFetcherSettings()
