import pytest
from PySide6.QtCore import Qt
from pyqtgraph import Point
from bganalyzer.ui.linked_view import LinkedValueViewBox


class Drag:
    def accept(self): pass
    def button(self): return Qt.MiddleButton
    def buttons(self): return Qt.MiddleButton
    def pos(self): return Point(150, 130)
    def lastPos(self): return Point(120, 100)
    def isFinish(self): return False
    def isStart(self): return False


@pytest.mark.parametrize("target", ["primary", "overlay"])
def test_middle_drag_moves_both_value_scales_by_same_fraction(qtbot, target):
    import pyqtgraph as pg
    primary = LinkedValueViewBox()
    widget = pg.PlotWidget(viewBox=primary)
    qtbot.addWidget(widget)
    overlay = LinkedValueViewBox(primary)
    widget.scene().addItem(overlay)
    overlay.setXLink(primary)
    widget.resize(700, 400)
    widget.show()
    qtbot.waitExposed(widget)
    overlay.setGeometry(primary.sceneBoundingRect())
    primary.setRange(xRange=(0, 100), yRange=(2, 12), padding=0)
    overlay.setYRange(-1, 3, padding=0)
    before = primary.viewRange()[1][:]
    getattr({"primary": primary, "overlay": overlay}[target], "mouseDragEvent")(Drag())
    after = primary.viewRange()[1]
    secondary = overlay.viewRange()[1]
    assert after != before
    assert (after[0] - before[0]) / 10 == pytest.approx((secondary[0] + 1) / 4)
    assert secondary[1] - secondary[0] == pytest.approx(4)
    assert overlay.viewRange()[0] == pytest.approx(primary.viewRange()[0])
