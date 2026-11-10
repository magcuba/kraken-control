import unittest
from types import SimpleNamespace
from dashboard import canvas, canvas_pixbuf, CurveGraph


class RenderTests(unittest.TestCase):
    def test_cairo_pixels_have_correct_colours(self):
        surface, cr = canvas(20, 10)
        cr.set_source_rgb(1, 0, 0)
        cr.paint()
        pixbuf = canvas_pixbuf(surface)
        self.assertEqual((pixbuf.get_width(), pixbuf.get_height()), (20, 10))
        self.assertEqual(pixbuf.get_pixels()[:4], bytes([255, 0, 0, 255]))

    def test_curve_renders_without_a_display(self):
        result = []
        dummy = SimpleNamespace(get_allocated_width=lambda:700, get_allocated_height=lambda:220,
                                temperature=34.5, get_points=lambda:[(30,40),(35,60),(40,80),(45,100)],
                                image=SimpleNamespace(set_from_pixbuf=result.append))
        dummy.xy = lambda t,d: CurveGraph.xy(dummy,t,d)
        CurveGraph.render(dummy)
        self.assertEqual(result[0].get_width(), 700)
        self.assertEqual(result[0].get_height(), 220)


if __name__ == '__main__':
    unittest.main()
