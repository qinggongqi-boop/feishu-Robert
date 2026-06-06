from __future__ import annotations

from images import cleanup_old_image_dirs, localize_report_images


class FakeImageResponse:
    headers = {"Content-Type": "image/jpeg"}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=65536):
        yield b"\xff\xd8\xfffake-jpeg"


class FakeHtmlResponse:
    headers = {"Content-Type": "text/html"}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=65536):
        yield b"<html></html>"


def test_localize_report_images_downloads_to_report_assets(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, headers, timeout, stream):
        calls.append((url, headers, timeout, stream))
        return FakeImageResponse()

    monkeypatch.setattr("images.requests.get", fake_get)
    items = [
        {
            "title": "新闻",
            "image_url": "https://example.com/cover.jpg",
            "image_urls": ["https://example.com/cover.jpg"],
        }
    ]

    count = localize_report_images(
        items,
        output_dir=tmp_path,
        target_date="2026-06-06",
        timeout_seconds=8,
        retries=1,
        user_agent="Test UA",
    )

    assert count == 1
    assert calls[0][0] == "https://example.com/cover.jpg"
    assert calls[0][1]["User-Agent"] == "Test UA"
    assert items[0]["image_url"].startswith("./assets/images/2026-06-06/01-")
    assert items[0]["cover"] == items[0]["image_url"]
    assert (tmp_path / items[0]["image_url"].removeprefix("./")).exists()


def test_localize_report_images_uses_placeholder_when_download_is_not_image(tmp_path, monkeypatch):
    monkeypatch.setattr("images.requests.get", lambda *args, **kwargs: FakeHtmlResponse())
    items = [{"image_url": "https://example.com/not-image", "image_urls": ["https://example.com/not-image"]}]

    count = localize_report_images(
        items,
        output_dir=tmp_path,
        target_date="2026-06-06",
        timeout_seconds=8,
        retries=1,
        user_agent="Test UA",
    )

    assert count == 0
    assert items[0]["image_url"] == ""
    assert items[0]["image_urls"] == []


def test_cleanup_old_image_dirs_keeps_recent_seven_days(tmp_path):
    old_dir = tmp_path / "assets" / "images" / "2026-05-30"
    recent_dir = tmp_path / "assets" / "images" / "2026-06-01"
    old_dir.mkdir(parents=True)
    recent_dir.mkdir(parents=True)
    (old_dir / "old.jpg").write_bytes(b"old")
    (recent_dir / "recent.jpg").write_bytes(b"recent")

    cleanup_old_image_dirs(tmp_path, target_date="2026-06-07", keep_days=7)

    assert not old_dir.exists()
    assert recent_dir.exists()
