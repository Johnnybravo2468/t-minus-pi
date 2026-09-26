"""Display drivers (Phase 3).

A display driver takes a :class:`~src.display_encoder.DisplayFrame` and shows it
on some output device. This is the layer that will eventually talk to the
physical LED matrix; for Windows development we only need simulated drivers.

    DisplayFrame  ->  DisplayDriver.render()  ->  output

The abstract :class:`DisplayDriver` is the seam that lets Phase 5 drop in a
``RaspberryPiLEDDisplay`` without changing the encoder or the app. A driver
knows about the output device; it does NOT know what an MBTA departure means.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

from src.display_encoder import DisplayFrame


class DisplayDriver(ABC):
    """Interface every display output must implement."""

    @abstractmethod
    def render(self, frame: DisplayFrame) -> None:
        """Show the frame on the output device."""
        raise NotImplementedError


class ConsoleDisplay(DisplayDriver):
    """Simplest driver: prints the frame rows as-is (no border)."""

    def render(self, frame: DisplayFrame) -> None:
        print(frame.as_text())


class SimulatedLEDDisplay(DisplayDriver):
    """Renders the frame inside a border, simulating the physical LED panel.

    Use this on Windows to verify the layout before buying/wiring the real
    matrix. ``clear=True`` wipes the screen before each render so repeated
    updates look like a live board.
    """

    def __init__(self, clear: bool = False):
        self.clear = clear

    def render(self, frame: DisplayFrame) -> None:
        if self.clear:
            os.system("cls" if os.name == "nt" else "clear")

        border = "+" + "-" * (frame.width + 2) + "+"
        lines = [border]
        for row in frame.rows:
            lines.append(f"| {row} |")
        lines.append(border)
        print("\n".join(lines))
