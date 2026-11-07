"""Raspberry Pi LED matrix display driver (hardware phase).

Drives real RGB LED panels with Henner Zeller's ``rpi-rgb-led-matrix`` library
(https://github.com/hzeller/rpi-rgb-led-matrix). It is the hardware counterpart
to the simulated :class:`~src.led_matrix.PixelMatrix` previews: it takes a
``PixelMatrix`` and pushes it to the panel, one pixel at a time.

Geometry: two 64x64 panels daisy-chained is ``rows=64, cols=64,
chain_length=2`` -> a 128x64 pixel canvas.

The heavy ``rgbmatrix`` binding is imported lazily so this module (and the whole
project) still imports and tests fine on Windows/dev machines without it. For
testing off-Pi you can either:
- pass a ``backend`` (used by unit tests with a fake), or
- pass ``use_emulator=True`` to use the drop-in ``RGBMatrixEmulator`` package.
"""

from __future__ import annotations

from typing import Optional, Tuple

from src.led_matrix import PixelMatrix

# Sensible defaults for two chained 64x64 panels on an Adafruit RGB Matrix HAT.
DEFAULT_ROWS = 64
DEFAULT_COLS = 64
DEFAULT_CHAIN = 2
DEFAULT_PARALLEL = 1


def _load_backend(use_emulator: bool):
    """Return (RGBMatrix, RGBMatrixOptions) from the real lib or the emulator."""
    if use_emulator:
        from RGBMatrixEmulator import RGBMatrix, RGBMatrixOptions
    else:
        # Only available on a Raspberry Pi with the library installed.
        from rgbmatrix import RGBMatrix, RGBMatrixOptions
    return RGBMatrix, RGBMatrixOptions


class RaspberryPiLEDDisplay:
    """Pushes a :class:`PixelMatrix` to physical RGB LED panels."""

    def __init__(
        self,
        rows: int = DEFAULT_ROWS,
        cols: int = DEFAULT_COLS,
        chain_length: int = DEFAULT_CHAIN,
        parallel: int = DEFAULT_PARALLEL,
        brightness: int = 60,
        hardware_mapping: str = "adafruit-hat",
        gpio_slowdown: int = 4,
        # A departure board does not need the panels scanned as fast as the
        # hardware can go. Capping the rate leaves quiet gaps so the Pi's
        # onboard Wi-Fi can stay associated.
        limit_refresh_hz: int = 100,
        drop_privileges: bool = True,
        use_emulator: bool = False,
        backend: Optional[Tuple[type, type]] = None,
    ):
        if backend is None:
            rgb_matrix_cls, options_cls = _load_backend(use_emulator)
        else:
            rgb_matrix_cls, options_cls = backend

        options = options_cls()
        options.rows = rows
        options.cols = cols
        options.chain_length = chain_length
        options.parallel = parallel
        options.brightness = brightness
        options.hardware_mapping = hardware_mapping
        # gpio_slowdown may not exist on every build; set defensively.
        try:
            options.gpio_slowdown = gpio_slowdown
        except AttributeError:
            pass
        try:
            options.limit_refresh_rate_hz = limit_refresh_hz
        except AttributeError:
            pass
        # By default the library drops root to the 'daemon' user after init for
        # security. That prevents later reads of a venv under the user's home
        # (breaking lazy imports like httpx->httpcore). Allow keeping privileges.
        try:
            options.drop_privileges = drop_privileges
        except AttributeError:
            pass

        self.width = cols * chain_length
        self.height = rows * parallel
        self._matrix = rgb_matrix_cls(options=options)
        self._canvas = self._matrix.CreateFrameCanvas()

    def render(self, pixel_matrix: PixelMatrix) -> None:
        """Blit a PixelMatrix to the panel and swap it in on the next refresh."""
        self._canvas.Clear()
        max_y = min(self.height, pixel_matrix.height)
        max_x = min(self.width, pixel_matrix.width)
        for y in range(max_y):
            for x in range(max_x):
                color = pixel_matrix.get_pixel(x, y)
                if color is not None:
                    self._canvas.SetPixel(x, y, color[0], color[1], color[2])
        self._canvas = self._matrix.SwapOnVSync(self._canvas)

    def clear(self) -> None:
        try:
            self._matrix.Clear()
        except Exception:
            pass
