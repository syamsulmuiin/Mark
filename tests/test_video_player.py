from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    spec = spec_from_file_location("video_player", ROOT / "desktop-companion/runtime/actions/video_player.py")
    if spec is None or spec.loader is None:
        raise AssertionError("could not load video_player module")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_path_expands_existing_file(tmp_path):
    sample = tmp_path / "sample.mp4"
    sample.write_bytes(b"video")
    module = load_module()
    assert module._local_path(str(sample)) == str(sample)


def test_stop_cancels_pending_open(monkeypatch):
    module = load_module()
    token = module._begin_open()
    module._begin_open()
    assert not module._still_wanted(token)


def test_direct_media_url_is_url():
    module = load_module()
    assert module._is_url("https://example.test/video.mp4")
    assert not module._is_url("video.mp4")
