from app.modules.audio_pipeline.application import workflow


def test_graph_has_segment_nodes_not_translation():
    nodes = set(workflow.audio_pipeline_graph.get_graph().nodes.keys())
    assert "segment_and_label" in nodes
    assert "build_segment_metadata" in nodes
    assert "build_translations" not in nodes
    assert "build_metadata" not in nodes
