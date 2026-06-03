from utils.widgets.launch_section import PAGE_SIZE, MAX_PAGES, page_count


def test_page_size_and_max():
    assert PAGE_SIZE == 4
    assert MAX_PAGES == 4


def test_page_count_reserves_a_landing_page_until_ceiling():
    # 0-3 -> 1, 4-7 -> 2, 8-11 -> 3, 12-15 -> 4, 16 -> 4
    expected = {0: 1, 1: 1, 3: 1, 4: 2, 7: 2, 8: 3, 11: 3, 12: 4, 15: 4, 16: 4}
    for n, pc in expected.items():
        assert page_count(n) == pc, f"n={n}"
