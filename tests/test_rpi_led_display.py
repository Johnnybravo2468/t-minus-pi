"""Tests for RaspberryPiLEDDisplay using a fake matrix backend (no hardware).

These verify the driver talks to the rpi-rgb-led-matrix API correctly:
options are configured, each lit pixel is pushed via SetPixel, and the canvas
is swapped on VSync.
"""

from src.led_matrix import PixelMatrix
from src.rpi_led_display import RaspberryPiLEDDisplay


class FakeOptions:
    pass


class FakeCanvas:
    def __init__(self):
        self.pixels = {}
        self.clear_count = 0

    def Clear(self):
        self.clear_count += 1

    def SetPixel(self, x, y, r, g, b):
        self.pixels[(x, y)] = (r, g, b)


class FakeMatrix:
    last_instance = None

    def __init__(self, options=None):
        self.options = options
        self.canvases = [FakeCanvas(), FakeCanvas()]
        self._created = 0
        self.swap_count = 0
        self.cleared = False
        FakeMatrix.last_instance = self

    def CreateFrameCanvas(self):
        canvas = self.canvases[self._created % len(self.canvases)]
        self._created += 1
        return canvas

    def SwapOnVSync(self, canvas):
        self.swap_count += 1
        # Return the other canvas, like the real double-buffered API.
        return self.canvases[self._created % len(self.canvases)]

    def Clear(self):
        self.cleared = True


def _backend():
    return (FakeMatrix, FakeOptions)


def test_options_configured_for_two_64x64_panels():
    display = RaspberryPiLEDDisplay(backend=_backend())
    opts = FakeMatrix.last_instance.options
    assert opts.rows == 64
    assert opts.cols == 64
    assert opts.chain_length == 2
    assert display.width == 128
    assert display.height == 64


def test_render_pushes_lit_pixels_and_swaps():
    display = RaspberryPiLEDDisplay(backend=_backend())
    matrix = PixelMatrix(128, 64)
    matrix.set_pixel(0, 0, (10, 20, 30))
    matrix.set_pixel(5, 7, (1, 2, 3))

    display.render(matrix)

    canvas = FakeMatrix.last_instance.canvases[0]
    assert canvas.pixels[(0, 0)] == (10, 20, 30)
    assert canvas.pixels[(5, 7)] == (1, 2, 3)
    # Only lit pixels are pushed (2 set above).
    assert len(canvas.pixels) == 2
    assert canvas.clear_count == 1
    assert FakeMatrix.last_instance.swap_count == 1


def test_render_ignores_pixels_outside_panel():
    display = RaspberryPiLEDDisplay(backend=_backend())
    # PixelMatrix larger than the panel: extra pixels must be skipped.
    matrix = PixelMatrix(200, 100)
    matrix.set_pixel(150, 90, (9, 9, 9))  # outside 128x64
    matrix.set_pixel(10, 10, (4, 4, 4))   # inside

    display.render(matrix)

    canvas = FakeMatrix.last_instance.canvases[0]
    assert (10, 10) in canvas.pixels
    assert (150, 90) not in canvas.pixels


def test_clear_calls_matrix_clear():
    display = RaspberryPiLEDDisplay(backend=_backend())
    display.clear()
    assert FakeMatrix.last_instance.cleared is True
