"""Streamlit app entry point for CoachAgent.

Only responsible for: calling UI rendering entry point (ui.render_app()).
No business logic.
"""

import logging
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

load_dotenv()


def main() -> None:
    """Main entry point for the Streamlit app."""
    from ui import render_app

    logger.info("Starting CoachAgent Streamlit app")
    render_app()


if __name__ == "__main__":
    main()
