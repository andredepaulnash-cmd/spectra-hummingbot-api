from utils.spectra_paper_guard import (
    is_read_only_post_path,
    read_only_post_paths,
    should_block_paper_mutation,
)


def test_known_query_posts_remain_available_in_paper_mode():
    for path in read_only_post_paths():
        assert is_read_only_post_path(path)
        assert not should_block_paper_mutation("POST", path)


def test_query_allowlist_does_not_match_prefixes_or_similar_paths():
    assert not is_read_only_post_path("/executors/search/extra")
    assert not is_read_only_post_path("/executors/")
    assert not is_read_only_post_path("/gateway/swap/execute")
    assert not is_read_only_post_path("/market-data/order-book/restart/kraken")


def test_execution_and_administration_mutations_are_blocked():
    blocked = (
        ( "POST", "/executors/"),
        ( "POST", "/trading/orders"),
        ( "POST", "/trading/account/kraken/leverage"),
        ( "POST", "/trading/account/kraken/position-mode"),
        ( "POST", "/gateway/swap/execute"),
        ( "POST", "/gateway/swap/execute-quote"),
        ( "POST", "/gateway/clmm/open"),
        ( "POST", "/gateway/clmm/add"),
        ( "POST", "/gateway/amm/add-liquidity"),
        ( "POST", "/bot-orchestration/start-bot"),
        ( "POST", "/bot-orchestration/deploy-v2-script"),
        ( "POST", "/docker/start-container/demo"),
        ( "POST", "/scripts/custom"),
        ( "DELETE", "/executors/positions/kraken/BTC-USD"),
        ( "DELETE", "/accounts/gateway/ethereum/0xabc"),
    )
    for method, path in blocked:
        assert should_block_paper_mutation(method, path), (method, path)


def test_only_post_queries_are_exempt():
    assert should_block_paper_mutation("PUT", "/portfolio/state")
    assert should_block_paper_mutation("PATCH", "/executors/search")
    assert should_block_paper_mutation("DELETE", "/trading/positions")
    assert not should_block_paper_mutation("GET", "/executors/")
    assert not should_block_paper_mutation("OPTIONS", "/trading/orders")


def test_query_parameters_do_not_expand_the_allowlist():
    assert not should_block_paper_mutation(
        "POST", "/executors/search?next=/executors/"
    )
    assert should_block_paper_mutation(
        "POST", "/executors/?redirect=/executors/search"
    )
