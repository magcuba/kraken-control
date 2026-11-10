import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import backend
from app import DEFAULT
from theme_editor import save_theme
from theme_renderer import THEMES, render, validate_theme, value_label


class ThemeTests(unittest.TestCase):
    def theme_config(self):
        c=copy.deepcopy(DEFAULT)
        c.update(screen='theme',theme=copy.deepcopy(THEMES['Nebula']))
        return backend.validate(c)

    def test_builtin_themes_render_at_lcd_resolution(self):
        values=dict(clock='12:47',cpu=52.6,gpu=33,liquid=31.7,cpu_load=45,gpu_load=25,ram=12)
        for theme in THEMES.values():
            with self.subTest(name=theme['name']):
                image=render(theme,values)
                self.assertEqual(image.size,(320,320))
                self.assertEqual(image.mode,'RGB')
                self.assertGreater(len(image.getcolors(320*320)),10)

    def test_missing_sensors_do_not_show_fake_values(self):
        self.assertEqual(value_label('gpu',{}),'—')
        self.assertEqual(render(THEMES['Nebula'],{}).size,(320,320))

    def test_invalid_element_rejected(self):
        for key,value in [('source','shell'),('radius',1000),('color','red')]:
            theme=copy.deepcopy(THEMES['Nebula'])
            theme['elements'][0][key]=value
            with self.assertRaises(ValueError):validate_theme(theme)

    def test_unsupported_version_and_oversized_elements(self):
        theme=copy.deepcopy(THEMES['Minimal'])
        theme['version']=2
        with self.assertRaises(ValueError):validate_theme(theme)
        theme['version']=1
        theme['elements']*=10
        with self.assertRaises(ValueError):validate_theme(theme)

    def test_gallery_save_roundtrip_and_safe_filename(self):
        theme=copy.deepcopy(THEMES['Minimal'])
        theme['name']='../../Mi tema'
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            p=save_theme(theme,root)
            self.assertEqual(p.parent,root)
            self.assertEqual(validate_theme(json.loads(p.read_text())),theme)

    def test_hidden_overlay_changes_output(self):
        theme=copy.deepcopy(THEMES['Minimal'])
        first=render(theme,dict(cpu=55)).tobytes()
        for element in theme['elements']:element['visible']=False
        self.assertNotEqual(first,render(theme,dict(cpu=55)).tobytes())

    def test_theme_service_uses_dynamic_renderer(self):
        c=self.theme_config()
        text=backend.unit_text(c)
        self.assertIn(str(backend.THEME_RENDERER),text)
        self.assertIn('Type=simple',text)
        self.assertNotIn('"fan" "speed"',text)
        self.assertNotIn('/usr/local/lib/kraken-control/cpu_display.py',text)
        self.assertIn('ExecStartPre=',backend.runtime_text(c))

    def test_background_is_copied_for_service(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            bg=root/'background.png'
            Image.new('RGB',(10,10),'red').save(bg)
            c=self.theme_config();c['theme']['background_image']=str(bg)
            with patch.object(backend,'THEME_RENDERER',root/'installed/renderer.py'),patch.object(backend,'THEME_DATA',root/'data'):
                backend.install_theme(c)
                config=Path(backend.theme_command(c)[-1])
                saved=json.loads(config.read_text())
                self.assertNotEqual(saved['background_image'],str(bg))
                bg.unlink()
                self.assertEqual(render(saved,{}).size,(320,320))

    def test_installed_renderer_is_not_copied_onto_itself(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            renderer=root/'theme_renderer.py'
            renderer.write_text('# installed renderer\n')
            config=self.theme_config()
            with patch.object(backend,'__file__',str(root/'backend.py')),patch.object(backend,'THEME_RENDERER',renderer),patch.object(backend,'THEME_DATA',root/'data'):
                backend.install_theme(config)
            self.assertEqual(renderer.read_text(),'# installed renderer\n')

    def test_runtime_override_restored_when_screen_start_fails(self):
        with tempfile.TemporaryDirectory() as d:
            runtime=Path(d)/'runtime.conf';runtime.write_text('previous runtime')
            c=copy.deepcopy(DEFAULT)
            def run(args,**kw):
                if 'start' in args and kw.get('check',True):raise RuntimeError('failure')
                return subprocess.CompletedProcess(args,0,'','')
            with patch.object(backend,'RUNTIME',runtime),patch.object(backend,'run',run):
                with self.assertRaises(RuntimeError):backend.perform('screen',c)
            self.assertEqual(runtime.read_text(),'previous runtime')

    def test_persistent_save_removes_temporary_override(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);runtime=root/'runtime.conf';runtime.write_text('preview')
            dropin=root/'saved.conf'
            def run(args,**kw):return subprocess.CompletedProcess(args,0,'','')
            with patch.object(backend,'RUNTIME',runtime),patch.object(backend,'DROPIN',dropin),patch.object(backend,'run',run),patch.object(backend,'install_theme'):
                backend.perform('save',self.theme_config())
            self.assertFalse(runtime.exists())
            self.assertIn(str(backend.THEME_RENDERER),dropin.read_text())


if __name__=='__main__':unittest.main()
