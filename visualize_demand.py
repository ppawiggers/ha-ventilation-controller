"""Visualize ventilation demand curves for each room."""

import matplotlib.pyplot as plt
import numpy as np
from config import load_config


def calculate_demand(humidity: float, target: float, multiplier: float) -> float:
    """Calculate demand for a given humidity level."""
    humidity_diff = humidity - target
    demand = humidity_diff * multiplier
    return max(0.0, min(100.0, demand))


def plot_demand_curves():
    """Plot demand curves for all rooms."""
    config = load_config()

    # Create humidity range from 0 to 100%
    humidity_range = np.linspace(0, 100, 200)

    plt.figure(figsize=(12, 8))

    # Plot each room's demand curve
    for room_key, room_config in config.rooms.items():
        curve = room_config.humidity_curve
        demands = [
            calculate_demand(h, curve.target_humidity, curve.multiplier)
            for h in humidity_range
        ]

        plt.plot(
            humidity_range,
            demands,
            label=f"{room_config.name} (target={curve.target_humidity}%, mult={curve.multiplier})",
            linewidth=2,
        )

        # Mark the target humidity with a vertical line
        plt.axvline(
            x=curve.target_humidity,
            linestyle="--",
            alpha=0.3,
            color=plt.gca().lines[-1].get_color(),
        )

    # Add minimum fan speed line
    plt.axhline(
        y=25, color="gray", linestyle=":", linewidth=1, label="Min fan speed (25%)"
    )

    # Formatting
    plt.xlabel("Room Humidity (%)", fontsize=12)
    plt.ylabel("Ventilation Demand (%)", fontsize=12)
    plt.title("Ventilation Demand vs. Humidity by Room", fontsize=14, fontweight="bold")
    plt.legend(loc="upper left", fontsize=10)
    plt.grid(True, alpha=0.3)
    plt.xlim(0, 100)
    plt.ylim(0, 105)

    # Add annotations
    plt.text(
        95,
        5,
        "Demand = (humidity - target) × multiplier",
        horizontalalignment="right",
        fontsize=9,
        style="italic",
        color="gray",
    )

    plt.tight_layout()
    plt.savefig("demand_curves.png", dpi=150, bbox_inches="tight")
    print("Graph saved to: demand_curves.png")
    plt.show()


if __name__ == "__main__":
    plot_demand_curves()
