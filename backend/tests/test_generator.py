from PIL import Image

import app.services.generator as generator
from app.services.generator import _prepare_vace_conditions, _wan_dimensions, _wan_frame_plan


def test_wan_uses_native_480p_for_landscape_and_portrait() -> None:
    assert _wan_dimensions(1280, 720) == (832, 480)
    assert _wan_dimensions(720, 1280) == (480, 832)


def test_wan_fast_dimensions_reduce_spatial_work() -> None:
    assert _wan_dimensions(1280, 720, "fast") == (480, 272)
    assert _wan_dimensions(720, 1280, "balanced") == (368, 656)


def test_wan_frame_plan_uses_four_k_plus_one_frames() -> None:
    assert _wan_frame_plan(3) == (49, 16)
    assert _wan_frame_plan(5) == (81, 16)
    frames, _ = _wan_frame_plan(4.25)
    assert (frames - 1) % 4 == 0
    assert frames <= 81


def test_wan_fast_frame_plan_reduces_temporal_work() -> None:
    assert _wan_frame_plan(5, "fast") == (41, 8)
    assert _wan_frame_plan(5, "balanced") == (61, 12)


def test_vace_conditions_preserve_five_tail_frames(monkeypatch, tmp_path) -> None:
    source_frames = [
        Image.new("RGB", (32, 24), (index, index, index))
        for index in range(8)
    ]
    monkeypatch.setattr("diffusers.utils.load_video", lambda _path: source_frames)

    video, mask = _prepare_vace_conditions(
        tmp_path / "previous.mp4",
        width=64,
        height=48,
        num_frames=13,
        continuity_frames=5,
    )

    assert len(video) == len(mask) == 13
    assert [frame.getpixel((0, 0))[0] for frame in video[:5]] == [3, 4, 5, 6, 7]
    assert all(frame.size == (64, 48) for frame in video)
    assert all(frame.getextrema() == (0, 0) for frame in mask[:5])
    assert all(frame.getextrema() == (255, 255) for frame in mask[5:])


def test_release_pipeline_offloads_components_and_clears_reference(monkeypatch) -> None:
    class Component:
        def __init__(self) -> None:
            self.devices: list[str] = []

        def to(self, device: str) -> None:
            self.devices.append(device)

    class Pipeline:
        def __init__(self) -> None:
            self.text_encoder = Component()
            self.transformer = Component()
            self.vae = Component()
            self.hooks_freed = False

        def maybe_free_model_hooks(self) -> None:
            self.hooks_freed = True

    pipeline = Pipeline()
    cache_cleared: list[bool] = []
    monkeypatch.setattr(generator, "_pipeline", pipeline)
    monkeypatch.setattr(generator, "_pipeline_kind", "vace")
    monkeypatch.setattr(generator, "_clear_cuda_cache", lambda: cache_cleared.append(True))

    generator._release_pipeline()

    assert pipeline.hooks_freed is True
    assert pipeline.text_encoder.devices == ["cpu"]
    assert pipeline.transformer.devices == ["cpu"]
    assert pipeline.vae.devices == ["cpu"]
    assert generator._pipeline is None
