"""Coordinate mouse navigation for overlaid plots with different value units."""
import pyqtgraph as pg


class LinkedValueViewBox(pg.ViewBox):
    def __init__(self, primary=None):
        super().__init__()
        self.primary = primary
        self.companions = []
        if primary is not None:
            primary.companions.append(self)

    def _navigate(self, handler, event, axis):
        old_lo, old_hi = self.viewRange()[1]
        peers = [(view, view.viewRange()[1][:]) for view in self.companions]
        handler(event, axis=axis)
        new_lo, new_hi = self.viewRange()[1]
        if old_hi <= old_lo or (old_lo, old_hi) == (new_lo, new_hi):
            return
        # Preserve the relative pixel position, not equality of mmol/L and U.
        shift = (new_lo - old_lo) / (old_hi - old_lo)
        scale = (new_hi - new_lo) / (old_hi - old_lo)
        for view, (lo, hi) in peers:
            span = hi - lo
            low = lo + shift * span
            view.setYRange(low, low + scale * span, padding=0)

    def mouseDragEvent(self, event, axis=None):
        if self.primary is not None:
            self.primary.mouseDragEvent(event, axis=axis)
        else:
            self._navigate(super().mouseDragEvent, event, axis)

    def wheelEvent(self, event, axis=None):
        if self.primary is not None:
            self.primary.wheelEvent(event, axis=axis)
        else:
            self._navigate(super().wheelEvent, event, axis)
