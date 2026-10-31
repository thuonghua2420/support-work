import base64
import io
import unittest
from unittest.mock import patch

from PIL import Image, PngImagePlugin

from autocompare_tool.image_compare import compare_images


def payload(image, *, metadata=None, name="test.png"):
    stream = io.BytesIO()
    image.save(stream, format="PNG", pnginfo=metadata)
    return {"name": name, "data_url": "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()}


class ImageCompareTests(unittest.TestCase):
    def test_identical_pixels_with_different_file_metadata(self):
        image = Image.new("RGB", (40, 30), "white")
        old = payload(image)
        self.assertEqual(compare_images(old, old)["verdict"], "BINARY IDENTICAL")
        info = PngImagePlugin.PngInfo()
        info.add_text("comment", "different metadata")
        result = compare_images(old, payload(image, metadata=info))
        self.assertEqual(result["verdict"], "PIXEL IDENTICAL")
        self.assertEqual(result["changed_pixels"], 0)
        self.assertEqual(result["regions"], [])

    def test_single_channel_single_pixel_changes_are_detected(self):
        for channel in range(4):
            old = Image.new("RGBA", (65, 65), (10, 10, 10, 10))
            new = old.copy()
            value = [10, 10, 10, 10]
            value[channel] = 11
            new.putpixel((64, 64), tuple(value))
            result = compare_images(payload(old), payload(new))
            self.assertEqual(result["changed_pixels"], 1)
            self.assertFalse(result["identical"])
            self.assertEqual(result["regions"], [[64, 64, 65, 65]])

    def test_missing_transparent_area_counts_and_canvas_corners_do_not(self):
        result = compare_images(payload(Image.new("RGBA", (10, 2))), payload(Image.new("RGBA", (2, 10))))
        self.assertEqual(result["total_pixels"], 36)
        self.assertEqual(result["changed_pixels"], 32)
        self.assertFalse(result["dimensions_identical"])

    def test_hidden_color_of_fully_transparent_pixels_is_not_a_difference(self):
        old = Image.new("RGBA", (20, 20), (255, 0, 0, 0))
        new = Image.new("RGBA", (20, 20), (0, 0, 255, 0))
        result = compare_images(payload(old), payload(new))
        self.assertEqual(result["changed_pixels"], 0)
        self.assertTrue(result["identical"])
        # A faintly visible pixel still counts.
        new.putpixel((3, 3), (0, 0, 255, 1))
        self.assertEqual(compare_images(payload(old), payload(new))["changed_pixels"], 1)

    def test_color_metadata_change_does_not_claim_identical(self):
        image = Image.new("RGB", (5, 5), "white")
        info = PngImagePlugin.PngInfo()
        info.add(b"gAMA", (45455).to_bytes(4, "big"))
        result = compare_images(payload(image), payload(image, metadata=info))
        self.assertTrue(result["pixels_identical"])
        self.assertFalse(result["color_metadata_identical"])
        self.assertFalse(result["identical"])

    def test_invalid_and_high_bit_depth_images_are_rejected(self):
        valid = payload(Image.new("RGB", (5, 5)))
        for invalid in (None, {"data_url": "bad"}, {"data_url": "data:image/png;base64,bm90IGFuIGltYWdl"}, payload(Image.new("I;16", (3, 3)))):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                compare_images(invalid, valid)

    def test_orientation_applied_before_comparison(self):
        source = Image.new("RGB", (3, 2), "white")
        source.putpixel((0, 0), (255, 0, 0))
        exif = Image.Exif()
        exif[274] = 6
        stream = io.BytesIO()
        source.save(stream, format="PNG", exif=exif)
        old = {"data_url": "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()}
        result = compare_images(old, payload(source.transpose(Image.Transpose.ROTATE_270)))
        self.assertTrue(result["identical"])
        self.assertEqual((result["old"]["width"], result["old"]["height"]), (2, 3))

    def test_animated_images_are_not_silently_reduced_to_first_frame(self):
        stream = io.BytesIO()
        Image.new("RGB", (4, 4), "white").save(stream, format="PNG", save_all=True,
            append_images=[Image.new("RGB", (4, 4), "black")], duration=100, loop=0)
        animated = {"data_url": "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()}
        with self.assertRaisesRegex(ValueError, "ảnh tĩnh"):
            compare_images(animated, animated)

    def test_dimension_limits_are_checked_before_rendering(self):
        old = payload(Image.new("RGB", (10, 2)))
        new = payload(Image.new("RGB", (2, 10)))
        with patch("autocompare_tool.image_compare.MAX_IMAGE_PIXELS", 10), self.assertRaisesRegex(ValueError, "triệu pixel mỗi ảnh"):
            compare_images(old, new)
        with patch("autocompare_tool.image_compare.MAX_CANVAS_PIXELS", 50), self.assertRaisesRegex(ValueError, "Khung so sánh"):
            compare_images(old, new)
