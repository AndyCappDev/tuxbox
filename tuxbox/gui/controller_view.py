#!/usr/bin/env python3
"""Controller visualization widget

Displays the selected TourBox model with highlighting for selected controls.
"""

import logging
import os
import re
from xml.etree import ElementTree as ET
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Signal, Qt, QRectF, QByteArray, QSize, QEvent
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtSvg import QSvgRenderer

from .theme import is_dark_theme, foreground_hex
from .controller_models import get_model_controls
from tuxbox.config_loader import DEFAULT_CONTROLLER_MODEL, VALID_CONTROLLER_MODELS

logger = logging.getLogger(__name__)

# The artwork is line art drawn in black, which disappears against a dark
# window background. On dark themes these ink colours are remapped to the
# palette foreground. The highlight fills (#fff6d5 cream, #00ffff cyan) are
# deliberately left alone - they are light by design and read well on both.
_INK_COLOURS = (b'#000000', b'#1a1a1a')


def _theme_svg(svg_data: bytes) -> bytes:
    """Recolour the artwork's black line work to suit the active palette

    Returns the data unchanged on light themes.
    """
    if not is_dark_theme():
        return svg_data

    ink = foreground_hex().encode('ascii')

    for colour in _INK_COLOURS:
        svg_data = svg_data.replace(b'stroke:' + colour, b'stroke:' + ink)
        svg_data = svg_data.replace(b'fill:' + colour, b'fill:' + ink)

    # Elements with no fill of their own (the control labels) fall back to
    # SVG's default of black. Set an inherited default on the root instead;
    # explicit fills in style="" still win over this presentation attribute.
    svg_data = re.sub(
        rb'(<svg\b[^>]*?)(\s*>)',
        rb'\1 fill="' + ink + rb'"\2',
        svg_data,
        count=1,
    )

    return svg_data


class ControllerView(QWidget):
    """Widget to display TourBox controller with button highlighting"""

    # Signal emitted when user clicks on a control
    control_clicked = Signal(str)  # control name

    def __init__(self, parent=None, model: str = DEFAULT_CONTROLLER_MODEL):
        super().__init__(parent)
        self._model = (
            model if model in VALID_CONTROLLER_MODELS else DEFAULT_CONTROLLER_MODEL
        )
        self._current_control = None
        self._current_is_modifier = False
        self._combo_control = None  # Additional control to highlight for modifier combos
        self._svg_renderer = None
        self._svg_path = None
        self._svg_data = None
        self._init_ui()
        self._load_svg()

    def _init_ui(self):
        """Initialize the UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # SVG rendering widget
        self.svg_widget = SVGControllerWidget(self)
        layout.addWidget(self.svg_widget)

    def _load_svg(self):
        """Load the TourBox SVG file"""
        # Get path to SVG file (relative to this module)
        self._svg_path = os.path.join(
            os.path.dirname(__file__),
            'assets',
            f'tourbox_{self._model}.svg'
        )

        if not os.path.exists(self._svg_path):
            logger.error(f"SVG file not found: {self._svg_path}")
            return

        # Load SVG data
        with open(self._svg_path, 'rb') as f:
            self._svg_data = _theme_svg(f.read())

        # Load SVG renderer
        self._svg_renderer = QSvgRenderer(QByteArray(self._svg_data))
        if not self._svg_renderer.isValid():
            logger.error(f"Invalid SVG file: {self._svg_path}")
            self._svg_renderer = None
            return

        # Pass renderer and data to the widget
        self.svg_widget.set_svg_data(self._svg_renderer, self._svg_data)
        logger.info(f"Loaded SVG from: {self._svg_path}")

    def set_model(self, model: str):
        """Switch artwork and restore the current selection on the new model."""
        self._model = (
            model if model in VALID_CONTROLLER_MODELS else DEFAULT_CONTROLLER_MODEL
        )
        self._load_svg()

        # Drop any selection the new model doesn't have (e.g. Side when
        # switching to Lite) so it isn't looked up in artwork that lacks it
        available = get_model_controls(self._model)
        if self._combo_control not in available:
            self._combo_control = None
        if self._current_control not in available:
            self.clear_highlight()
            return
        self.svg_widget.set_highlighted_control(
            self._current_control, self._current_is_modifier, self._combo_control
        )

    def changeEvent(self, event):
        """Re-theme the artwork when the application palette changes"""
        if event.type() in (QEvent.PaletteChange, QEvent.ApplicationPaletteChange):
            self._load_svg()
            # Rebuild the highlight against the newly themed artwork
            self.svg_widget.set_highlighted_control(
                self._current_control, self._current_is_modifier, self._combo_control
            )
        super().changeEvent(event)

    def highlight_control(self, control_name: str, is_modifier: bool = False, combo_control: str = None):
        """Highlight a specific control on the image

        Args:
            control_name: Name of the control to highlight (e.g., 'side', 'knob_cw')
            is_modifier: Whether this control is a modifier button
            combo_control: Optional additional control to highlight (for modifier combinations)
        """
        self._current_control = control_name
        self._current_is_modifier = is_modifier
        self._combo_control = combo_control
        self.svg_widget.set_highlighted_control(control_name, is_modifier, combo_control)
        logger.debug(f"Highlighted control: {control_name} (modifier: {is_modifier}, combo: {combo_control})")

    def clear_highlight(self):
        """Clear the current highlight"""
        self._current_control = None
        self._current_is_modifier = False
        self._combo_control = None
        self.svg_widget.set_highlighted_control(None, False, None)
        logger.debug("Cleared highlight")


class SVGControllerWidget(QWidget):
    """Custom widget for rendering SVG with control highlighting"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._base_renderer = None
        self._highlight_renderer = None
        self._svg_data = None
        self._highlighted_control = None
        self.setMinimumSize(300, 220)

    def sizeHint(self):
        """Preferred size - the SVG aspect ratio at a comfortable height"""
        return QSize(469, 410)

    def set_svg_data(self, renderer: QSvgRenderer, svg_data: bytes):
        """Set the SVG renderer and raw data"""
        self._base_renderer = renderer
        self._svg_data = svg_data
        self.update()

    def set_highlighted_control(self, control_name: str, is_modifier: bool = False, combo_control: str = None):
        """Set which control(s) to highlight

        Args:
            control_name: Primary control to highlight
            is_modifier: Whether the primary control is a modifier
            combo_control: Optional additional control to highlight from controls layer
        """
        self._highlighted_control = control_name

        # Create a renderer with the selected control(s) visible
        if control_name and self._svg_data:
            try:
                # Build list of controls to highlight
                controls_to_highlight = [(control_name, is_modifier)]
                if combo_control:
                    # Combo control is always from controls layer
                    controls_to_highlight.append((combo_control, False))

                # Parse SVG and make the controls visible
                modified_svg = self._make_controls_visible(self._svg_data, controls_to_highlight)
                if modified_svg:
                    self._highlight_renderer = QSvgRenderer(QByteArray(modified_svg))
                else:
                    self._highlight_renderer = None
            except Exception as e:
                logger.error(f"Failed to create highlight renderer: {e}")
                self._highlight_renderer = None
        else:
            self._highlight_renderer = None

        self.update()

    def _make_controls_visible(self, svg_data: bytes, controls: list) -> bytes:
        """Modify SVG to show multiple specified controls

        Args:
            svg_data: The raw SVG data
            controls: List of tuples (control_id, is_modifier)
        """
        try:
            # Register namespaces to preserve them
            ET.register_namespace('', 'http://www.w3.org/2000/svg')
            # Qt needs the xlink prefix preserved when highlight SVGs use <use>.
            ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')
            ET.register_namespace('inkscape', 'http://www.inkscape.org/namespaces/inkscape')
            ET.register_namespace('sodipodi', 'http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd')

            root = ET.fromstring(svg_data)
            inkscape_ns = '{http://www.inkscape.org/namespaces/inkscape}'

            # Process each control
            for control_id, is_modifier in controls:
                # Determine which layer to search in
                layer_name = 'modifiers' if is_modifier else 'controls'

                # In modifiers layer, IDs are prefixed with "m_"
                search_id = f"m_{control_id}" if is_modifier else control_id

                # Find the layer
                layer_elem = None
                for elem in root.iter():
                    if elem.get(f'{inkscape_ns}label') == layer_name:
                        layer_elem = elem
                        break

                if layer_elem is None:
                    logger.warning(f"Layer '{layer_name}' not found in SVG")
                    continue

                # Find the control element by ID within that layer
                control_elem = None
                for elem in layer_elem.iter():
                    if elem.get('id') == search_id:
                        control_elem = elem
                        break

                if control_elem is None:
                    # Callers only pass controls the current model has, so a
                    # miss here means the artwork is missing a group
                    logger.warning(f"Control element '{search_id}' not found in layer '{layer_name}'")
                    continue

                # Change the control's style from hidden to visible
                current_style = control_elem.get('style', '')

                # Remove display:none or set display:inline
                if 'display:none' in current_style:
                    new_style = current_style.replace('display:none', 'display:inline')
                    control_elem.set('style', new_style)
                elif 'display' not in current_style:
                    # No display property, add it
                    control_elem.set('style', current_style + ';display:inline' if current_style else 'display:inline')
                else:
                    # Has display property but not none, just make sure it's inline
                    control_elem.set('style', current_style.replace('display:inline', 'display:inline'))

            # Convert back to bytes
            return ET.tostring(root, encoding='utf-8')

        except Exception as e:
            logger.error(f"Failed to modify SVG: {e}")
            return None

    def _make_control_visible(self, svg_data: bytes, control_id: str, is_modifier: bool = False) -> bytes:
        """Modify SVG to show only the specified control

        Args:
            svg_data: The raw SVG data
            control_id: The control name (e.g., 'side', 'top')
            is_modifier: If True, search in 'modifiers' layer; otherwise 'controls' layer
        """
        try:
            # Register namespaces to preserve them
            ET.register_namespace('', 'http://www.w3.org/2000/svg')
            ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')
            ET.register_namespace('inkscape', 'http://www.inkscape.org/namespaces/inkscape')
            ET.register_namespace('sodipodi', 'http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd')

            root = ET.fromstring(svg_data)

            # Determine which layer to search in
            layer_name = 'modifiers' if is_modifier else 'controls'

            # In modifiers layer, IDs are prefixed with "m_"
            search_id = f"m_{control_id}" if is_modifier else control_id

            # Find the layer first
            inkscape_ns = '{http://www.inkscape.org/namespaces/inkscape}'
            layer_elem = None
            for elem in root.iter():
                if elem.get(f'{inkscape_ns}label') == layer_name:
                    layer_elem = elem
                    break

            if layer_elem is None:
                logger.warning(f"Layer '{layer_name}' not found in SVG")
                return None

            # Find the control element by ID within that layer
            control_elem = None
            for elem in layer_elem.iter():
                if elem.get('id') == search_id:
                    control_elem = elem
                    break

            if control_elem is None:
                logger.warning(f"Control element '{search_id}' not found in layer '{layer_name}'")
                return None

            # Simply change the control's style from hidden to visible
            current_style = control_elem.get('style', '')

            # Remove display:none or set display:inline
            if 'display:none' in current_style:
                new_style = current_style.replace('display:none', 'display:inline')
                control_elem.set('style', new_style)
            elif 'display' not in current_style:
                # No display property, add it
                control_elem.set('style', current_style + ';display:inline' if current_style else 'display:inline')
            else:
                # Has display property but not none, just make sure it's inline
                control_elem.set('style', current_style.replace('display:inline', 'display:inline'))

            # Convert back to bytes
            return ET.tostring(root, encoding='utf-8')

        except Exception as e:
            logger.error(f"Failed to modify SVG: {e}")
            return None

    def paintEvent(self, event):
        """Paint the SVG with highlighting"""
        if not self._base_renderer:
            # Show placeholder if no SVG loaded
            painter = QPainter(self)
            painter.fillRect(self.rect(), self.palette().color(QPalette.Base))
            painter.setPen(self.palette().color(QPalette.WindowText))
            painter.drawText(
                self.rect(),
                Qt.AlignCenter,
                "TourBox\n(SVG not found)"
            )
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # Calculate scaling to fit widget while maintaining aspect ratio
        svg_size = self._base_renderer.defaultSize()
        widget_size = self.size()

        scale_x = widget_size.width() / svg_size.width()
        scale_y = widget_size.height() / svg_size.height()
        scale = min(scale_x, scale_y)

        # Calculate centered position
        scaled_width = svg_size.width() * scale
        scaled_height = svg_size.height() * scale
        x = (widget_size.width() - scaled_width) / 2
        y = (widget_size.height() - scaled_height) / 2

        target_rect = QRectF(x, y, scaled_width, scaled_height)

        # Render base SVG (shows background, controls layer is hidden)
        self._base_renderer.render(painter, target_rect)

        # Render highlight overlay (shows only the selected control)
        if self._highlight_renderer:
            self._highlight_renderer.render(painter, target_rect)
