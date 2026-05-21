from utils.cc_stdout_parser import (
    AvatarRecord, ZoneRecord, parse_avatar_record, parse_latest_zone,
)


AVATAR_LINE = (
    "__handleAvatarChooserDone: 101194667, 'Flossbud', "
    "('dss', 'ls', 'm', 'f', (0.0, 0.403921, 0.647058, 1.0), "
    "(1.0, 1.0, 1.0, 1.0), (0.0, 0.403921, 0.647058, 1.0), "
    "(0.0, 0.403921, 0.647058, 1.0), 263, 27, 236, 27, 155, 27, "
    "(0.0, 0.403921, 0.647058, 1.0), 0, 0), 0\n"
)


def test_parse_avatar_record_extracts_fields():
    rec = parse_avatar_record(AVATAR_LINE)
    assert rec is not None
    assert rec.doid == 101194667
    assert rec.name == "Flossbud"
    assert rec.head_code == "dss"
    # 5 RGB tuples (skin, gloves, shirt, shorts, accent)
    assert len(rec.dna_colors) == 5
    assert rec.dna_colors[0] == (0.0, 0.403921, 0.647058)


def test_parse_avatar_record_returns_last_match():
    text = (
        AVATAR_LINE
        + AVATAR_LINE.replace("'Flossbud'", "'Newer'").replace("dss", "css")
    )
    rec = parse_avatar_record(text)
    assert rec.name == "Newer"
    assert rec.head_code == "css"


def test_parse_avatar_record_returns_none_on_empty():
    assert parse_avatar_record("") is None
    assert parse_avatar_record("nothing matching here\n") is None


def test_parse_latest_zone_returns_last_for_av_id():
    text = (
        ":ToontownClientRepository: enterPlayGame hoodId:2000 zoneId:2000 avId:-1\n"
        ":ToontownClientRepository: enterPlayGame hoodId:2000 zoneId:2100 avId:101194667\n"
        ":ToontownClientRepository: enterPlayGame hoodId:3000 zoneId:3100 avId:999999\n"
        ":ToontownClientRepository: enterPlayGame hoodId:4000 zoneId:4100 avId:101194667\n"
    )
    rec = parse_latest_zone(text, av_id=101194667)
    assert rec is not None
    assert rec.hood_id == 4000
    assert rec.zone_id == 4100


def test_parse_latest_zone_returns_none_when_av_id_absent():
    text = ":ToontownClientRepository: enterPlayGame hoodId:2000 zoneId:2000 avId:-1\n"
    assert parse_latest_zone(text, av_id=101194667) is None
