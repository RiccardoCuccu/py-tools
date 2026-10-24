"""Tests for image_framer: config loading and validation, sizing math, framing geometry
and colors, EXIF/transparency handling, text placement, output-overwrite protection, and
the main() entry point. All images and configs live in tmp_path.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from PIL import Image

import image_framer as imf

RED = (255, 0, 0)
WHITE = (255, 255, 255)
BLUE = (0, 0, 255)
GREEN = (0, 255, 0)
BLACK = (0, 0, 0)


def make_image(path: Path, size=(40, 20), color=BLUE, mode="RGB", **save_kwargs) -> Path:
    """Create a solid-color image file."""
    fill = color if mode == "RGB" else color + (255,)
    Image.new(mode, size, fill).save(path, **save_kwargs)
    return path


def base_settings(tmp_path: Path, **overrides) -> dict:
    """Validated settings pointing at files inside tmp_path (no text by default)."""
    config = imf.get_default_config()
    config.update(
        input_path=str(tmp_path / "in.png"),
        output_path=str(tmp_path / "out.png"),
        top_text="", bottom_text="", left_text="", right_text="",
        outer_frame_thickness=10,
        inner_frame_thickness=5,
        target_inner_size=100,
    )
    config.update(overrides)
    return imf.validate_config(config)


def write_config(path: Path, data) -> Path:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


class TestLoadConfig:
    def test_defaults_fill_missing_keys(self, tmp_path):
        cfg = write_config(tmp_path / "c.yaml", {"font_size": 12})
        config = imf.load_config(str(cfg))
        assert config["font_size"] == 12
        assert config["quality"] == imf.get_default_config()["quality"]

    def test_relative_paths_resolved_against_config_dir(self, tmp_path):
        (tmp_path / "sub").mkdir()
        cfg = write_config(
            tmp_path / "sub" / "c.yaml",
            {"input_path": "a.jpg", "output_path": "out/b.jpg", "font_path": "f.ttf"},
        )
        config = imf.load_config(str(cfg))
        assert Path(config["input_path"]) == tmp_path / "sub" / "a.jpg"
        assert Path(config["output_path"]) == tmp_path / "sub" / "out" / "b.jpg"
        assert Path(config["font_path"]) == tmp_path / "sub" / "f.ttf"

    def test_default_relative_paths_also_follow_config_dir(self, tmp_path):
        cfg = write_config(tmp_path / "c.yaml", {})
        config = imf.load_config(str(cfg))
        assert Path(config["input_path"]) == tmp_path / "input.jpg"

    def test_absolute_paths_are_kept(self, tmp_path):
        absolute = str(tmp_path / "abs.jpg")
        cfg = write_config(tmp_path / "c.yaml", {"input_path": absolute})
        assert imf.load_config(str(cfg))["input_path"] == absolute

    def test_empty_font_path_stays_empty(self, tmp_path):
        cfg = write_config(tmp_path / "c.yaml", {"font_path": ""})
        assert imf.load_config(str(cfg))["font_path"] == ""

    def test_empty_file_uses_defaults(self, tmp_path):
        cfg = tmp_path / "c.yaml"
        cfg.write_text("", encoding="utf-8")
        assert imf.load_config(str(cfg))["quality"] == 95

    def test_unknown_key_rejected(self, tmp_path):
        cfg = write_config(tmp_path / "c.yaml", {"outer_frame_colour": [1, 2, 3]})
        with pytest.raises(imf.ConfigError, match="outer_frame_colour"):
            imf.load_config(str(cfg))

    def test_non_mapping_rejected(self, tmp_path):
        cfg = tmp_path / "c.yaml"
        cfg.write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(imf.ConfigError, match="mapping"):
            imf.load_config(str(cfg))

    def test_invalid_yaml_rejected(self, tmp_path):
        cfg = tmp_path / "c.yaml"
        cfg.write_text("a: [unclosed", encoding="utf-8")
        with pytest.raises(imf.ConfigError, match="parse"):
            imf.load_config(str(cfg))

    def test_missing_file_rejected(self, tmp_path):
        with pytest.raises(imf.ConfigError, match="not found"):
            imf.load_config(str(tmp_path / "nope.yaml"))

    def test_generated_default_config_round_trips(self, tmp_path):
        target = tmp_path / "config_default.yaml"
        imf.create_default_config(str(target))
        settings = imf.validate_config(imf.load_config(str(target)))
        assert settings["outer_frame_color"] == RED
        assert settings["top_text"] == "TOP"


class TestValidateConfig:
    def _cfg(self, **overrides):
        config = imf.get_default_config()
        config.update(overrides)
        return config

    def test_colors_become_tuples(self):
        settings = imf.validate_config(self._cfg())
        assert settings["outer_frame_color"] == RED
        assert isinstance(settings["text_color"], tuple)

    @pytest.mark.parametrize(
        "bad",
        [[255, 0], [255, 0, 0, 0], [256, 0, 0], [-1, 0, 0], ["a", 0, 0], [1.5, 0, 0],
         [True, 0, 0], "red", None, 5],
    )
    def test_bad_colors_rejected(self, bad):
        with pytest.raises(imf.ConfigError, match="outer_frame_color"):
            imf.validate_config(self._cfg(outer_frame_color=bad))

    @pytest.mark.parametrize(
        ("key", "bad"),
        [
            ("quality", 0), ("quality", 101), ("quality", "high"), ("quality", True),
            ("target_inner_size", 0), ("target_inner_size", -5), ("target_inner_size", 10.5),
            ("outer_frame_thickness", -1), ("inner_frame_thickness", None),
            ("font_size", 0),
        ],
    )
    def test_bad_numbers_rejected(self, key, bad):
        with pytest.raises(imf.ConfigError, match=key):
            imf.validate_config(self._cfg(**{key: bad}))

    def test_zero_thickness_allowed(self):
        settings = imf.validate_config(
            self._cfg(outer_frame_thickness=0, inner_frame_thickness=0)
        )
        assert settings["outer_frame_thickness"] == 0

    def test_null_text_becomes_empty_and_numbers_become_strings(self):
        settings = imf.validate_config(self._cfg(top_text=None, bottom_text=2024))
        assert settings["top_text"] == ""
        assert settings["bottom_text"] == "2024"

    @pytest.mark.parametrize("key", ["input_path", "output_path"])
    def test_empty_required_paths_rejected(self, key):
        with pytest.raises(imf.ConfigError, match=key):
            imf.validate_config(self._cfg(**{key: ""}))

    def test_input_is_not_mutated(self):
        config = self._cfg()
        imf.validate_config(config)
        assert config["outer_frame_color"] == [255, 0, 0]


class TestFindOrCreateConfig:
    def test_creates_default_and_exits_zero_when_no_yaml(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            imf.find_or_create_config(tmp_path)
        assert exc.value.code == 0
        assert (tmp_path / imf.DEFAULT_CONFIG_NAME).is_file()

    def test_exits_one_and_creates_nothing_when_yaml_present(self, tmp_path):
        (tmp_path / "mine.yml").write_text("quality: 90\n", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            imf.find_or_create_config(tmp_path)
        assert exc.value.code == 1
        assert not (tmp_path / imf.DEFAULT_CONFIG_NAME).exists()


class TestScaledSize:
    @pytest.mark.parametrize(
        ("size", "target", "expected"),
        [
            ((200, 100), 100, (100, 50)),
            ((100, 200), 100, (50, 100)),
            ((50, 50), 100, (100, 100)),
            ((1, 5000), 1000, (1, 1000)),
            ((5000, 1), 1000, (1000, 1)),
            ((3, 2), 10, (10, 7)),
        ],
    )
    def test_longest_side_matches_target(self, size, target, expected):
        assert imf.scaled_size(*size, target) == expected


class TestProcessImageGeometry:
    def test_output_size_and_nested_frame_colors(self, tmp_path):
        make_image(tmp_path / "in.png", (40, 20), BLUE)
        settings = base_settings(
            tmp_path, outer_frame_color=RED, inner_frame_color=GREEN, padding_color=BLACK
        )
        imf.process_image(**settings)

        with Image.open(tmp_path / "out.png") as out:
            assert out.size == (100 + 2 * 5 + 2 * 10,) * 2
            assert out.getpixel((0, 0)) == RED
            assert out.getpixel((12, 12)) == GREEN  # inside inner frame
            assert out.getpixel((15 + 2, 15 + 2)) == BLACK  # padding bar (top of square)
            assert out.getpixel((60, 60)) == BLUE  # image center

    def test_extreme_aspect_ratio_does_not_crash(self, tmp_path):
        make_image(tmp_path / "in.png", (1, 400), BLUE)
        imf.process_image(**base_settings(tmp_path))
        with Image.open(tmp_path / "out.png") as out:
            assert out.size[0] == out.size[1]

    def test_zero_thickness_frames(self, tmp_path):
        make_image(tmp_path / "in.png", (30, 30), BLUE)
        imf.process_image(
            **base_settings(tmp_path, outer_frame_thickness=0, inner_frame_thickness=0)
        )
        with Image.open(tmp_path / "out.png") as out:
            assert out.size == (100, 100)

    def test_transparent_png_is_flattened_onto_padding_color(self, tmp_path):
        Image.new("RGBA", (40, 40), (0, 0, 255, 0)).save(tmp_path / "in.png")
        imf.process_image(**base_settings(tmp_path, padding_color=WHITE))
        with Image.open(tmp_path / "out.png") as out:
            assert out.getpixel((60, 60)) == WHITE

    def test_exif_orientation_is_applied(self, tmp_path):
        # 40x20 landscape tagged "rotate 90": the upright image is 20x40 portrait
        src = Image.new("RGB", (40, 20), BLUE)
        for x in range(20):
            for y in range(20):
                src.putpixel((x, y), RED)
        exif = Image.Exif()
        exif[0x0112] = 6
        src.save(tmp_path / "in.jpg", exif=exif)
        imf.process_image(**base_settings(tmp_path, input_path=str(tmp_path / "in.jpg"),
                                          output_path=str(tmp_path / "out.png"),
                                          outer_frame_color=BLACK, inner_frame_color=BLACK,
                                          padding_color=WHITE))
        with Image.open(tmp_path / "out.png") as out:
            # Portrait content is centered with white bars on the left and right
            assert out.getpixel((15 + 5, 60)) == WHITE
            assert out.getpixel((60, 15 + 5)) != WHITE

    def test_input_file_handle_is_released(self, tmp_path):
        source = make_image(tmp_path / "in.png")
        imf.process_image(**base_settings(tmp_path))
        source.unlink()  # fails on Windows if the handle is still open
        assert not source.exists()


class TestOutputSafety:
    def test_same_path_refused_and_input_untouched(self, tmp_path):
        source = make_image(tmp_path / "in.png")
        before = source.read_bytes()
        settings = base_settings(tmp_path, output_path=str(source))
        with pytest.raises(ValueError, match="differ"):
            imf.process_image(**settings)
        assert source.read_bytes() == before

    def test_same_file_via_dotdot_path_refused(self, tmp_path):
        source = make_image(tmp_path / "in.png")
        (tmp_path / "sub").mkdir()
        settings = base_settings(
            tmp_path, output_path=str(tmp_path / "sub" / ".." / "in.png")
        )
        with pytest.raises(ValueError):
            imf.process_image(**settings)
        assert source.is_file()

    def test_corrupt_input_raises_oserror_and_writes_nothing(self, tmp_path):
        (tmp_path / "in.png").write_bytes(b"not an image")
        with pytest.raises(OSError):
            imf.process_image(**base_settings(tmp_path))
        assert not (tmp_path / "out.png").exists()

    def test_missing_input_raises(self, tmp_path):
        with pytest.raises(OSError):
            imf.process_image(**base_settings(tmp_path))


def count_pixels(img: Image.Image, box: tuple[int, int, int, int], color) -> int:
    """Count pixels of an exact color inside box (left, top, right, bottom)."""
    raw = img.crop(box).convert("RGB").tobytes()
    target = bytes(color)
    return sum(1 for i in range(0, len(raw), 3) if raw[i:i + 3] == target)


class TestText:
    def _render(self, tmp_path, **overrides):
        make_image(tmp_path / "in.png", (40, 40), BLUE)
        settings = base_settings(
            tmp_path,
            outer_frame_thickness=40,
            inner_frame_thickness=0,
            outer_frame_color=BLACK,
            text_color=GREEN,
            font_size=24,
            **overrides,
        )
        imf.process_image(**settings)
        return Image.open(tmp_path / "out.png")

    def test_no_text_means_no_text_pixels(self, tmp_path):
        with self._render(tmp_path) as out:
            assert count_pixels(out, (0, 0, *out.size), GREEN) == 0

    def test_top_text_stays_inside_top_band(self, tmp_path):
        with self._render(tmp_path, top_text="TOP") as out:
            width, _ = out.size
            assert count_pixels(out, (0, 0, width, 40), GREEN) > 0
            assert count_pixels(out, (0, 40, width, out.size[1]), GREEN) == 0

    def test_bottom_text_stays_inside_bottom_band(self, tmp_path):
        with self._render(tmp_path, bottom_text="BOTTOM") as out:
            width, height = out.size
            assert count_pixels(out, (0, height - 40, width, height), GREEN) > 0
            assert count_pixels(out, (0, 0, width, height - 40), GREEN) == 0

    def test_left_and_right_text_stay_inside_side_bands(self, tmp_path):
        with self._render(tmp_path, left_text="LEFT") as out:
            width, height = out.size
            assert count_pixels(out, (0, 0, 40, height), GREEN) > 0
            assert count_pixels(out, (40, 0, width, height), GREEN) == 0
        with self._render(tmp_path, right_text="RIGHT") as out:
            width, height = out.size
            assert count_pixels(out, (width - 40, 0, width, height), GREEN) > 0
            assert count_pixels(out, (0, 0, width - 40, height), GREEN) == 0

    def test_top_text_is_horizontally_centered(self, tmp_path):
        with self._render(tmp_path, top_text="MMMM") as out:
            width, _ = out.size
            xs = [x for x in range(width) if count_pixels(out, (x, 0, x + 1, 40), GREEN)]
            assert abs((min(xs) + max(xs)) / 2 - (width - 1) / 2) <= 2


class TestFonts:
    def test_missing_custom_font_falls_back_with_warning(self, tmp_path, capsys):
        font = imf.load_font(str(tmp_path / "missing.ttf"), 20)
        assert font is not None
        assert "WARNING" in capsys.readouterr().out

    def test_empty_font_path_uses_default_font_silently(self, capsys):
        assert imf.load_font("", 20) is not None
        assert "Could not load" not in capsys.readouterr().out


class TestMain:
    def _setup(self, tmp_path, **config):
        make_image(tmp_path / "in.png", (40, 20), BLUE)
        data = {"input_path": "in.png", "output_path": "out.png",
                "outer_frame_thickness": 4, "inner_frame_thickness": 2,
                "target_inner_size": 50, "top_text": "", "bottom_text": "",
                "left_text": "", "right_text": ""}
        data.update(config)
        return write_config(tmp_path / "c.yaml", data)

    def test_success_writes_output(self, tmp_path, capsys):
        cfg = self._setup(tmp_path)
        assert imf.main(["-c", str(cfg)]) == 0
        assert (tmp_path / "out.png").is_file()
        assert "processed successfully" in capsys.readouterr().out

    def test_cli_overrides_config_paths(self, tmp_path):
        cfg = self._setup(tmp_path)
        other_in = make_image(tmp_path / "other.png", (10, 10), RED)
        other_out = tmp_path / "other_out.png"
        assert imf.main(["-c", str(cfg), "-i", str(other_in), "-o", str(other_out)]) == 0
        assert other_out.is_file()
        assert not (tmp_path / "out.png").exists()

    def test_output_equal_to_input_is_an_error_and_keeps_input(self, tmp_path, capsys):
        cfg = self._setup(tmp_path, output_path="in.png")
        before = (tmp_path / "in.png").read_bytes()
        assert imf.main(["-c", str(cfg)]) == 1
        assert (tmp_path / "in.png").read_bytes() == before
        assert "ERROR" in capsys.readouterr().out

    def test_bad_config_value_is_an_error(self, tmp_path, capsys):
        cfg = self._setup(tmp_path, quality=500)
        assert imf.main(["-c", str(cfg)]) == 1
        assert "quality" in capsys.readouterr().out

    def test_missing_config_is_an_error(self, tmp_path):
        assert imf.main(["-c", str(tmp_path / "nope.yaml")]) == 1

    def test_missing_input_image_is_an_error(self, tmp_path):
        cfg = self._setup(tmp_path, input_path="absent.png")
        assert imf.main(["-c", str(cfg)]) == 1
        assert not (tmp_path / "out.png").exists()

    def test_unsupported_output_extension_is_an_error(self, tmp_path):
        cfg = self._setup(tmp_path, output_path="out.unknownext")
        assert imf.main(["-c", str(cfg)]) == 1
