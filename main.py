"""Main entry point for ventilation control system."""

import os
import logging

from ha import HomeAssistantAPI
from config import VentilationConfig
from controller import VentilationController

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)

logger = logging.getLogger(__name__)


def main():
    """Run ventilation control cycle."""
    # Initialize components
    logger.info("Initializing ventilation control system")

    ha = HomeAssistantAPI(
        ha_url=os.environ["HA_URL"],
        ha_token=os.environ["HA_TOKEN"],
    )

    config = VentilationConfig()
    controller = VentilationController(ha, config)

    # Execute control cycle
    current_state = controller.read_current_state()
    target_state = controller.calculate_required_state(current_state)
    controller.apply_state(target_state)

    logger.info("Ventilation control cycle completed")


if __name__ == "__main__":
    main()
