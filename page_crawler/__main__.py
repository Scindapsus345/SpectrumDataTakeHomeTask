import asyncio
import logging

from page_crawler.runner import Runner
from page_crawler.settings import AppSettings


def main() -> None:
    settings = AppSettings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(Runner(settings).run())


if __name__ == "__main__":
    main()
