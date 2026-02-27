import inspect

from quant_scanner.cli import parse_args
from quant_scanner.screener_engine import apply_filters


def test_dry_run_flag():
    args = parse_args(["--dry-run"])
    assert args.dry_run is True


def test_default_args():
    args = parse_args([])
    assert args.dry_run is False
    assert args.exchange == "kucoin,okx,gate"
    assert args.min_mcap == 20_000_000
    assert args.max_mcap == 150_000_000
    assert args.min_beta == 1.0
    assert args.min_corr == 0.6
    assert args.min_volume == 1_000_000
    assert args.max_amihud == 1e-5
    assert args.no_cache is False


def test_serve_flag():
    assert parse_args(["--serve"]).serve is True


def test_default_serve_false():
    assert parse_args([]).serve is False


def test_port_flag():
    assert parse_args(["--port", "9090"]).port == 9090


def test_default_port():
    assert parse_args([]).port == 8080


def test_host_flag():
    assert parse_args(["--host", "0.0.0.0"]).host == "0.0.0.0"


def test_default_host():
    assert parse_args([]).host == "127.0.0.1"


def test_refresh_interval_flag():
    assert parse_args(["--refresh-interval", "60"]).refresh_interval == 60


def test_default_refresh_interval():
    assert parse_args([]).refresh_interval == 300


def test_cli_defaults_match_screener():
    """CLI default values match apply_filters signature defaults."""
    args = parse_args([])
    sig = inspect.signature(apply_filters)
    assert args.min_beta == sig.parameters["min_beta"].default
    assert args.min_corr == sig.parameters["min_correlation"].default
    assert args.max_amihud == sig.parameters["max_amihud"].default
