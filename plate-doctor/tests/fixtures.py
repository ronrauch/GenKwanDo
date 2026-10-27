"""A tiny synthetic ComfyUI save-format graph that exercises everything ui_to_api must handle. Written for these
tests; it is not any vendor's workflow."""


def _n(i, typ, inputs, widgets=None, mode=0):
    return {"id": i, "type": typ, "inputs": inputs, "widgets_values": widgets or [], "mode": mode}


def _link(name, lid):
    return {"name": name, "type": "*", "link": lid}


def _wid(name, lid=None, typ="*"):
    return {"name": name, "type": typ, "widget": {"name": name}, "link": lid}


def hdr_like_ui_graph() -> dict:
    nodes = [
        _n(1, "LoadVideo", [_wid("file"), _wid("upload", typ="IMAGEUPLOAD")], ["x.mp4", "image"]),
        _n(2, "GetVideoComponents", [_link("video", 1)]),
        _n(4, "GetImageSize", [_link("image", 2)]),
        _n(3, "EmptyLTXVLatentVideo", [_wid("width", 3), _wid("height"), _wid("batch_size")], [999, 32, 1]),
        _n(5, "RandomNoise", [_wid("noise_seed")], [42, "fixed"]),
        _n(6, "LTXVHDRDecodePostprocess", [_link("image", 4), _wid("exposure"), _wid("save_exr"), _wid("output_dir"),
                                           _wid("filename_prefix"), _wid("half_precision")],
           [7.1, True, "output/old", "frame", True]),
        _n(7, "CreateVideo", [_link("images", 5), _link("audio", 6), _wid("fps")], [30]),
        _n(8, "SaveVideo", [_link("video", 7), _wid("filename_prefix"), _wid("format"), _wid("codec")],
           ["output", "auto", "auto"]),
        _n(9, "Note", [], ["a note"]),
        _n(10, "GemmaAPITextEncode", [_link("api_key", 8), _wid("prompt")], [""]),     # dead branch: feeds nothing
        _n(11, "PrimitiveString", [_wid("value")], [""]),
        _n(12, "MutedThing", [_wid("v")], [1], mode=2),
    ]
    links = [
        [1, 1, 0, 2, 0, "VIDEO"], [2, 2, 0, 4, 0, "IMAGE"], [3, 4, 0, 3, 0, "INT"], [4, 3, 0, 6, 0, "LATENT"],
        [5, 6, 1, 7, 0, "IMAGE"], [6, 2, 1, 7, 1, "AUDIO"], [7, 7, 0, 8, 0, "VIDEO"], [8, 11, 0, 10, 0, "STRING"],
    ]
    # link ids referenced by node inputs: map them to the table above
    ref = {"video@2": 1, "image@4": 2, "width@3": 3, "image@6": 4, "images@7": 5, "audio@7": 6, "video@8": 7, "api_key@10": 8}
    for n in nodes:
        for inp in n["inputs"]:
            inp["link"] = ref.get(f"{inp['name']}@{n['id']}")
    return {"nodes": nodes, "links": links}
