from quant_scanner.cli import parse_args


def test_dry_run_flag():
    args = parse_args(["--dry-run"])
    assert args.dry_run is True


def test_default_args():
    args = parse_args([])
    assert args.dry_run is False
    assert args.exchange == "binance"
    assert args.min_mcap == 20_000_000
    assert args.max_mcap == 150_000_000
    assert args.min_beta == 1.5
    assert args.min_corr == 0.7
    assert args.min_volume == 1_000_000
    assert args.no_cache is False
