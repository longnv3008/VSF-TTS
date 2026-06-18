from app.modules.audio_pipeline.application.worker import _map_state_to_job_paths


def test_map_state_uses_segments_manifest():
    paths = _map_state_to_job_paths({"segments_manifest_path": "/data/metadata/b1_segments.csv"})
    assert paths["metadata_path"] == "/data/metadata/b1_segments.csv"
    assert paths["manifest_path"] == "/data/metadata/b1_segments.csv"
    assert paths["output_path"] == "/data/metadata/b1_segments.csv"
    assert paths["translation_path"] is None


def test_map_state_handles_missing():
    paths = _map_state_to_job_paths({})
    assert paths["metadata_path"] is None
    assert paths["translation_path"] is None
