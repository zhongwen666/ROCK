import pytest

from rock.utils.format import convert_to_gb, parse_memory_size


def test_bytes_without_unit():
    assert parse_memory_size("100") == 100
    assert parse_memory_size("0") == 0
    assert parse_memory_size("1024") == 1024


def test_bytes_with_b_unit():
    assert parse_memory_size("100b") == 100
    assert parse_memory_size("100B") == 100
    assert parse_memory_size("0b") == 0


def test_kilobytes():
    assert parse_memory_size("1k") == 1024
    assert parse_memory_size("1K") == 1024
    assert parse_memory_size("1kb") == 1024
    assert parse_memory_size("1KB") == 1024
    assert parse_memory_size("2k") == 2048


def test_megabytes():
    assert parse_memory_size("1m") == 1024**2
    assert parse_memory_size("1M") == 1024**2
    assert parse_memory_size("1mb") == 1024**2
    assert parse_memory_size("1MB") == 1024**2
    assert parse_memory_size("2m") == 2 * 1024**2


def test_gigabytes():
    assert parse_memory_size("1g") == 1024**3
    assert parse_memory_size("1G") == 1024**3
    assert parse_memory_size("1gb") == 1024**3
    assert parse_memory_size("1GB") == 1024**3
    assert parse_memory_size("2g") == 2 * 1024**3


def test_terabytes():
    assert parse_memory_size("1t") == 1024**4
    assert parse_memory_size("1T") == 1024**4
    assert parse_memory_size("1tb") == 1024**4
    assert parse_memory_size("1TB") == 1024**4


def test_decimal_values():
    assert parse_memory_size("1.5k") == int(1.5 * 1024)
    assert parse_memory_size("2.5m") == int(2.5 * 1024**2)
    assert parse_memory_size("0.5g") == int(0.5 * 1024**3)


def test_whitespace_handling():
    assert parse_memory_size(" 100 ") == 100
    assert parse_memory_size(" 1k ") == 1024
    assert parse_memory_size("1 k") == 1024
    assert parse_memory_size(" 1 mb ") == 1024**2


def test_invalid_format():
    with pytest.raises(ValueError, match="Invalid memory size format"):
        parse_memory_size("abc")
    with pytest.raises(ValueError, match="Invalid memory size format"):
        parse_memory_size("1.2.3k")
    with pytest.raises(ValueError, match="Invalid memory size format"):
        parse_memory_size("")


def test_unknown_unit():
    with pytest.raises(ValueError, match="Unknown memory unit"):
        parse_memory_size("100x")
    with pytest.raises(ValueError, match="Unknown memory unit"):
        parse_memory_size("100pb")


def test_edge_cases():
    assert parse_memory_size("0.0") == 0
    assert parse_memory_size("0.0k") == 0
    assert parse_memory_size("1000") == 1000


def test_convert_to_gb_from_bytes():
    assert convert_to_gb("1073741824") == "1.00g"
    assert convert_to_gb("536870912") == "0.50g"


def test_convert_to_gb_from_kilobytes():
    assert convert_to_gb("1048576k") == "1.00g"
    assert convert_to_gb("2097152kb") == "2.00g"


def test_convert_to_gb_from_megabytes():
    assert convert_to_gb("1024m") == "1.00g"
    assert convert_to_gb("512mb") == "0.50g"
    assert convert_to_gb("2048M") == "2.00g"


def test_convert_to_gb_from_gigabytes():
    assert convert_to_gb("1g") == "1.00g"
    assert convert_to_gb("2.5gb") == "2.50g"
    assert convert_to_gb("0.25G") == "0.25g"


def test_convert_to_gb_from_terabytes():
    assert convert_to_gb("1t") == "1024.00g"
    assert convert_to_gb("0.5tb") == "512.00g"


def test_convert_to_gb_small_values():
    assert convert_to_gb("100m") == "0.10g"
    assert convert_to_gb("1m") == "0.00g"


def test_convert_to_gb_with_whitespace():
    assert convert_to_gb(" 1024m ") == "1.00g"
    assert convert_to_gb("2 g") == "2.00g"
