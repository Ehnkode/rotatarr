import logging
import os

import uvicorn


class HideStatusPolling(logging.Filter):
    """Drop access log lines for /api/state: the Docker health check and the open web UI ask every minute."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/api/state " not in record.getMessage()


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("uvicorn.access").addFilter(HideStatusPolling())
    uvicorn.run("rotatarr.web:app", host="0.0.0.0", port=int(os.environ.get("PORT", "7373")))


if __name__ == "__main__":
    main()
