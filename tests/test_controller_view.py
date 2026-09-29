"""Regression checks for model artwork, settings persistence and application."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from tuxbox.config_loader import load_device_config
from tuxbox.gui.controller_view import ControllerView
from tuxbox.gui.device_config_writer import save_device_settings
from tuxbox.gui.device_settings_dialog import DeviceSettingsDialog
from tuxbox.gui.main_window import TuxBoxConfigWindow
from tuxbox.gui.controls_list import ControlsList
from tuxbox.gui.control_editor import ControlEditor, ComboConfigDialog
from tuxbox.gui.controller_models import get_model_controls


LITE_CONTROLS = (
    'top', 'tall', 'short', 'c1', 'c2', 'tour',
    'scroll_up', 'scroll_down', 'scroll_click',
    'knob_cw', 'knob_ccw', 'knob_click',
)
LITE_MODIFIERS = ('top', 'tall', 'short', 'c1', 'c2', 'tour',
                  'scroll_click', 'knob_click')
ASSET = Path(__file__).resolve().parents[1] / 'tuxbox/gui/assets/tourbox_lite.svg'


class ControllerViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.palette = self.app.palette()

    def tearDown(self):
        self.app.setPalette(self.palette)
        self.app.processEvents()

    def test_svg_contract(self):
        self.assertEqual(get_model_controls('lite'), LITE_CONTROLS)
        root = ET.parse(ASSET).getroot()
        ids = [element.get('id') for element in root.iter() if element.get('id')]
        self.assertEqual(len(ids), len(set(ids)))
        namespace = '{http://www.inkscape.org/namespaces/inkscape}'
        for layer, expected in [('controls', LITE_CONTROLS),
                                ('modifiers', tuple('m_' + c for c in LITE_MODIFIERS))]:
            group = next(e for e in root.iter() if e.get(namespace + 'label') == layer)
            self.assertEqual({e.get('id') for e in group}, set(expected))
            for element in group:
                self.assertIn('display:none', element.get('style', ''))

    def test_every_control_and_modifier_renders(self):
        view = ControllerView(model='lite')
        base = self.render(view.svg_widget._base_renderer)
        centres = {'top': (220, 90), 'tall': (330, 330), 'short': (402, 350),
                   'c1': (341, 161), 'c2': (395, 198), 'tour': (140, 321),
                   'scroll': (95, 140), 'knob': (237, 227)}
        for control, modifier in [(c, False) for c in LITE_CONTROLS] + [
                (c, True) for c in LITE_MODIFIERS]:
            with self.subTest(control=control, modifier=modifier):
                view.highlight_control(control, modifier)
                renderer = view.svg_widget._highlight_renderer
                self.assertTrue(renderer.isValid())
                rendered = self.render(renderer)
                self.assertNotEqual(rendered, base)
                shape = control.split('_')[0]
                colour = '#00ffff' if modifier else '#fff6d5'
                self.assertEqual(rendered.pixelColor(*centres[shape]).name(), colour)
        view.close()

    @staticmethod
    def render(renderer):
        image = QImage(480, 455, QImage.Format_ARGB32)
        image.fill(Qt.white)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        return image

    def test_combination_reveals_both_groups(self):
        view = ControllerView(model='lite')
        data = view.svg_widget._make_controls_visible(
            view._svg_data, [('tall', True), ('knob_cw', False)])
        root = ET.fromstring(data)
        visible = {e.get('id') for e in root.iter()
                   if 'display:inline' in e.get('style', '')}
        self.assertEqual(visible, {'m_tall', 'knob_cw'})
        view.close()

    def test_model_switch_preserves_selection_and_clear_removes_overlay(self):
        view = ControllerView()
        view.highlight_control('tall', True, 'knob_cw')
        view.set_model('lite')
        self.assertTrue(view._svg_path.endswith('tourbox_lite.svg'))
        self.assertEqual(view._current_control, 'tall')
        self.assertTrue(view.svg_widget._highlight_renderer.isValid())
        view.set_model('elite')
        self.assertTrue(view._svg_path.endswith('tourbox_elite.svg'))
        self.assertTrue(view.svg_widget._highlight_renderer.isValid())
        view.clear_highlight()
        self.assertIsNone(view.svg_widget._highlight_renderer)
        view.close()

    def test_unknown_model_uses_elite(self):
        view = ControllerView(model='unknown')
        self.assertTrue(view._svg_path.endswith('tourbox_elite.svg'))
        view.set_model('unknown')
        self.assertTrue(view._svg_renderer.isValid())
        view.close()

    def test_absent_control_removes_previous_lite_highlight(self):
        view = ControllerView(model='lite')
        view.highlight_control('top')
        view.highlight_control('side')
        self.assertEqual(self.render(view.svg_widget._highlight_renderer),
                         self.render(view.svg_widget._base_renderer))
        view.close()

    def test_main_window_loads_model_and_control_selection(self):
        from tuxbox.config_loader import Profile
        with patch('tuxbox.gui.main_window.load_device_config',
                   return_value={'controller_model': 'lite'}):
            window = TuxBoxConfigWindow()
            profile = Profile(name='default', mapping={})
            window.current_profile = profile
            window.controls_list.load_profile(profile)
            self.assertEqual(self.visible_controls(window.controls_list), list(LITE_CONTROLS))
            window.controls_list.select_control('tall')
            self.assertTrue(window.controller_view._svg_path.endswith('tourbox_lite.svg'))
            self.assertEqual(window.controller_view._current_control, 'tall')
            self.assertTrue(window.controller_view.svg_widget._highlight_renderer.isValid())
            window.close()

    @staticmethod
    def visible_controls(controls):
        return [controls.table.item(row, 0).data(Qt.UserRole)
                for row in range(controls.table.rowCount())
                if not controls.table.isRowHidden(row)]

    def test_model_switch_filters_controls_preserving_selection_and_edits(self):
        from tuxbox.config_loader import Profile
        profile = Profile(name='default', mapping={},
                          mapping_comments={'side': 'Keep this mapping'})
        controls = ControlsList()
        controls.load_profile(profile)
        controls.table.item(0, 1).setText('Unsaved display edit')
        controls.select_control('side')
        controls.set_model('lite')
        self.assertEqual(self.visible_controls(controls), list(LITE_CONTROLS))
        self.assertEqual(controls.table.currentItem().data(Qt.UserRole), 'top')
        controls.select_control('side')
        self.assertEqual(controls.table.currentItem().data(Qt.UserRole), 'top')
        controls.select_control('tall')
        controls.set_model('elite')
        self.assertEqual(len(self.visible_controls(controls)), 20)
        self.assertEqual(controls.table.currentItem().data(Qt.UserRole), 'tall')
        self.assertEqual(controls.table.item(0, 1).text(), 'Unsaved display edit')
        self.assertEqual(profile.mapping_comments['side'], 'Keep this mapping')
        controls.close()

    def test_profile_reload_keeps_lite_filter(self):
        from tuxbox.config_loader import Profile
        controls = ControlsList(model='lite')
        for name in ('default', 'drawing'):
            controls.load_profile(Profile(name=name, mapping={}))
            self.assertEqual(self.visible_controls(controls), list(LITE_CONTROLS))
        controls.close()

    def test_combination_picker_offers_only_model_controls(self):
        dialog = ComboConfigDialog(modifier_name='tall', exclude_controls={'top'},
                                   available_controls=get_model_controls('lite'))
        offered = [dialog.control_combo.itemText(i)
                   for i in range(1, dialog.control_combo.count())]
        self.assertEqual(offered, [c for c in LITE_CONTROLS if c not in ('tall', 'top')])
        dialog.close()

    def test_hidden_combinations_survive_model_switch(self):
        editor = ControlEditor()
        editor.set_model('lite')
        editor.load_control('tall', 'KEY_A', modifier_combos={
            'dial_cw': ('KEY_B', 'Keep for Elite'),
            'knob_cw': ('KEY_C', 'Lite combo'),
        })
        self.assertTrue(editor.combos_table.isRowHidden(0))
        self.assertFalse(editor.combos_table.isRowHidden(1))
        self.assertEqual(editor.combos_table.currentRow(), 1)
        emitted = []
        editor.modifier_config_changed.connect(
            lambda control, config: emitted.append(config)
        )
        editor._on_apply()
        self.assertEqual(emitted[-1]['combos']['dial_cw'], ('KEY_B', 'Keep for Elite'))
        editor.set_model('elite')
        self.assertFalse(editor.combos_table.isRowHidden(0))
        self.assertEqual(editor.combos_table.item(0, 1).data(Qt.UserRole), 'KEY_B')
        self.assertEqual(editor.combos_table.item(0, 2).text(), 'Keep for Elite')
        editor.close()

    def test_palette_change_rethemes_and_restores_combination(self):
        view = ControllerView(model='lite')
        view.show()
        view.highlight_control('tall', True, 'knob_cw')
        dark = QPalette(self.palette)
        dark.setColor(QPalette.Window, QColor('#202325'))
        dark.setColor(QPalette.WindowText, QColor('#eff0f1'))
        self.app.setPalette(dark)
        self.app.processEvents()
        self.assertIn(b'stroke:#eff0f1', view._svg_data)
        self.assertNotIn(b'stroke:#000000', view._svg_data)
        self.assertIn(b'fill:#fff6d5', view._svg_data)
        self.assertIn(b'fill:#00ffff', view._svg_data)
        self.assertTrue(view.svg_widget._highlight_renderer.isValid())
        view.close()

    def test_settings_round_trip_preserves_comments_and_other_settings(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'config.conf'
            path.write_text('# Keep this comment\n[device]\nconnection = usb\n'
                            'custom_key = keep\n\n[service]\nrestart_command = custom\n')
            self.assertTrue(save_device_settings({'controller_model': 'lite'}, str(path))[0])
            self.assertEqual(load_device_config(str(path))['controller_model'], 'lite')
            self.assertIn('# Keep this comment', path.read_text())
            self.assertIn('custom_key = keep', path.read_text())
            self.assertIn('restart_command = custom', path.read_text())
            self.assertTrue(save_device_settings({'controller_model': None}, str(path))[0])
            self.assertNotIn('controller_model', load_device_config(str(path)))
            self.assertEqual(load_device_config(str(path))['connection'], 'usb')

    def test_invalid_config_model_falls_back(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'config.conf'
            path.write_text('[device]\ncontroller_model = future\n')
            self.assertNotIn('controller_model', load_device_config(str(path)))
            path.write_text('[device]\ncontroller_model = LITE # display only\n')
            self.assertEqual(load_device_config(str(path))['controller_model'], 'lite')

    def test_dialog_reports_only_changed_model_and_default_removal(self):
        with patch('tuxbox.gui.device_settings_dialog.load_device_config', return_value={}):
            dialog = DeviceSettingsDialog()
            self.assertEqual(dialog.get_changes(), {})
            dialog.model_combo.setCurrentIndex(dialog.model_combo.findData('lite'))
            self.assertEqual(dialog.get_changes(), {'controller_model': 'lite'})
            dialog.close()
        with patch('tuxbox.gui.device_settings_dialog.load_device_config',
                   return_value={'controller_model': 'lite'}):
            dialog = DeviceSettingsDialog()
            self.assertEqual(dialog.model_combo.currentData(), 'lite')
            dialog.model_combo.setCurrentIndex(dialog.model_combo.findData('elite'))
            self.assertEqual(dialog.get_changes(), {'controller_model': None})
            dialog.close()

    def apply_settings(self, changes, success=True):
        owner = SimpleNamespace(controller_view=Mock(), control_editor=Mock(),
                                controls_list=Mock(), statusBar=Mock(return_value=Mock()),
                                _on_restart_driver=Mock())
        with patch('tuxbox.gui.device_settings_dialog.DeviceSettingsDialog') as dialog, \
                patch('tuxbox.gui.device_config_writer.save_device_settings',
                      return_value=(success, 'result')), \
                patch('tuxbox.gui.main_window.cleanup_old_backups'), \
                patch.object(QMessageBox, 'question', return_value=QMessageBox.No) as question, \
                patch.object(QMessageBox, 'warning'):
            dialog.return_value.exec.return_value = QDialog.Accepted
            dialog.return_value.get_changes.return_value = changes
            TuxBoxConfigWindow._on_menu_settings(owner)
            return owner, question.call_count

    def test_artwork_only_save_does_not_prompt_for_restart(self):
        owner, prompts = self.apply_settings({'controller_model': 'lite'})
        owner.controller_view.set_model.assert_called_once_with('lite')
        owner.controls_list.set_model.assert_called_once_with('lite')
        owner.control_editor.set_model.assert_called_once_with('lite')
        self.assertEqual(prompts, 0)

    def test_mixed_save_applies_artwork_and_prompts_for_driver_restart(self):
        owner, prompts = self.apply_settings({'controller_model': None, 'connection': 'usb'})
        owner.controller_view.set_model.assert_called_once_with('elite')
        owner.controls_list.set_model.assert_called_once_with('elite')
        self.assertEqual(prompts, 1)

    def test_failed_save_does_not_change_artwork(self):
        owner, prompts = self.apply_settings({'controller_model': 'lite'}, success=False)
        owner.controller_view.set_model.assert_not_called()
        owner.controls_list.set_model.assert_not_called()
        self.assertEqual(prompts, 0)


if __name__ == '__main__':
    unittest.main()
