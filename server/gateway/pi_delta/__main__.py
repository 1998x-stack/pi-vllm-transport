"""Run the gateway on Ubuntu loopback: python -m pi_delta."""
import os

import uvicorn

from .app import Settings


def main():
    Settings.from_env()  # fail closed before exposing the port
    uvicorn.run(
        "pi_delta.app:make_app",
        factory=True,
        host=os.getenv("PI_DELTA_HOST", "127.0.0.1"),
        port=int(os.getenv("PI_DELTA_PORT", "18080")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
