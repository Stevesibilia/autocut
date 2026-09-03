from datetime import UTC, datetime
from pathlib import Path

from autocut.core.manifest import Manifest, Segment, SourceFile


def test_manifest_roundtrip(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    m = Manifest(created_at=now, updated_at=now, sources=[Path("/footage")], output_dir=tmp_path)
    m.files["abc"] = SourceFile(
        id="abc",
        path=Path("/footage/DJI_0001.MP4"),
        duration_s=20.0,
        width=3840,
        height=2160,
        fps=25.0,
        codec="h264",
        pix_fmt="yuv420p",
        source_class="drone",
        telemetry="dji_embedded_srt",
    )
    m.segments["abc:0"] = Segment(id="abc:0", file_id="abc", start_s=1.0, end_s=19.0)
    out = tmp_path / "manifest.json"
    m.save(out)
    back = Manifest.load(out)
    assert back.files["abc"].source_class == "drone"
    assert back.segments["abc:0"].outcome == "candidate"
    assert not out.with_suffix(".json.tmp").exists()
