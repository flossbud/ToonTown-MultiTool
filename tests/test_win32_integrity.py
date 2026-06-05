from utils.win32_integrity import Capability, classify_integrity


def test_higher_target_is_blocked():
    assert classify_integrity(own_il=0x2000, target_il=0x3000) is Capability.BLOCKED_UIPI


def test_equal_target_is_ok():
    assert classify_integrity(own_il=0x3000, target_il=0x3000) is Capability.OK


def test_lower_target_is_ok():
    assert classify_integrity(own_il=0x3000, target_il=0x2000) is Capability.OK


def test_unreadable_own_or_target_is_unknown():
    assert classify_integrity(own_il=None, target_il=0x3000) is Capability.UNKNOWN
    assert classify_integrity(own_il=0x2000, target_il=None) is Capability.UNKNOWN
