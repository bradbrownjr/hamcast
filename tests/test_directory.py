from hamcast.directory import parse_dmr, parse_ysf


def test_parse_ysf():
    text = "#comment\n62148;US-XLXUFB;XLXUFB;97.107.140.110;42000;002;\nbad;line\n"
    assert parse_ysf(text) == [{"id": "62148", "name": "US-XLXUFB", "description": "XLXUFB",
                                "host": "97.107.140.110", "port": 42000}]


def test_parse_dmr():
    text = "# Name ID Host Password Port\nDMR+_IPSC2-NEWENGLAND\t109387\t45.76.167.203\tPASSWORD\t55555\n\n"
    assert parse_dmr(text) == [{"name": "DMR+_IPSC2-NEWENGLAND", "id": "109387",
                                "host": "45.76.167.203", "password": "PASSWORD", "port": 55555}]
