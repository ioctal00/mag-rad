from master_regimes_infra.cli import build_parser


def test_cli_parser_builds() -> None:
    parser = build_parser()
    assert parser.prog == "master-regimes-infra"
