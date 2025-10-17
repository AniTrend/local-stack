from mergedeep import merge


def test_deep_merge_overlay():
    base = {
        "services": {
            "s": {
                "environment": {
                    "A": "1",
                    "B": "2",
                }
            }
        },
        "volumes": {
            "data": {"driver": "local"}
        },
    }

    overlay = {
        "services": {
            "s": {
                "environment": {
                    "B": "override",
                    "C": "3",
                }
            }
        },
        "volumes": {
            "extra": {"driver": "local"}
        },
    }

    expected = {
        "services": {
            "s": {
                "environment": {
                    "A": "1",
                    "B": "override",
                    "C": "3",
                }
            }
        },
        "volumes": {
            "data": {"driver": "local"},
            "extra": {"driver": "local"},
        },
    }

    merged = base.copy()
    merge(merged, overlay)
    assert merged == expected
