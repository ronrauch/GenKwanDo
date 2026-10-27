import json

import pytest

from cutting_room_lite import graph as G
from cutting_room_lite.planner import plan_windows

W = plan_windows(0, 30)


def build(k, **kw):
    args = dict(cover_name="cover.png", audio_name=f"w{k}.wav", prompt="P", seed=42, project="demo")
    args.update(kw)
    return G.build_window_graph(W[k], **args)


def test_window_zero_uses_the_cover_as_guide():
    g = build(0)
    assert g["6"]["inputs"]["image"] == "cover.png"
    assert g["15"]["inputs"]["image"] == ["6", 0]
    assert G.GUIDE_NODE not in g
    assert g["7"]["inputs"]["audio"] == "w0.wav"
    assert g["15"]["inputs"]["audio"] == ["7", 0]


def test_inputs_are_substituted():
    g = build(1, guide_name="g.png", seed=7, size=1024)
    n = g["8"]["inputs"]
    assert n["prompt"] == "P" and n["width"] == n["height"] == 1024
    assert n["length"] == W[1].render_frames == 241
    assert g["9"]["inputs"]["noise_seed"] == 7
    assert g["17"]["inputs"]["filename_prefix"] == "cutting-room-lite/demo_w1_s7"


def test_later_windows_guide_from_the_previous_last_frame_but_keep_the_cover_as_reference():
    g = build(2, guide_name="last.png")
    assert g[G.GUIDE_NODE]["inputs"]["image"] == "last.png"
    assert g["15"]["inputs"]["image"] == [G.GUIDE_NODE, 0]
    assert g["8"]["inputs"]["ref_images.ref_image_0"] == ["6", 0]
    assert g["6"]["inputs"]["image"] == "cover.png"


def test_later_windows_need_a_guide():
    with pytest.raises(ValueError):
        build(1)


def test_template_is_not_mutated_between_builds():
    build(0, seed=1)
    build(1, guide_name="x.png", seed=2)
    assert G.load_template()["9"]["inputs"]["noise_seed"] == 1
    assert G.GUIDE_NODE not in G.load_template()


def test_every_link_points_at_a_real_node():
    g = build(1, guide_name="x.png")
    for nid, node in g.items():
        for v in node["inputs"].values():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                assert v[0] in g, f"node {nid} links to missing node {v[0]}"


def test_proven_settings_survive():
    g = build(0)
    assert g["10"]["inputs"]["sampler_name"] == "res_multistep"
    assert g["11"]["inputs"]["scheduler"] == "kl_optimal" and g["11"]["inputs"]["steps"] == 8
    assert "turbo_4step" in g["2"]["inputs"]["lora_name"]
    assert g["8"]["inputs"]["ref_image_size"] == "match"


def test_project_name_is_made_filename_safe():
    g = build(0, project="my/../cover name")
    assert "/" not in g["17"]["inputs"]["filename_prefix"].split("/", 1)[1]


def test_describe_summarises_without_the_whole_graph():
    d = G.describe(build(0))
    assert d["frames"] == 240 and d["size"] == "1248x1248" and d["steps"] == 8
    json.dumps(d)
