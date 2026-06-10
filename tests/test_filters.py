from scoring.filters import _AddressBloomFilter


class _AlwaysPositiveFilter:
    def add(self, value: str) -> None:
        return None

    def __contains__(self, value: str) -> bool:
        return True


def test_bloom_blacklist_confirms_against_exact_set():
    blacklist = _AddressBloomFilter()
    blacklist._filter = _AlwaysPositiveFilter()

    listed = "0x000000000000000000000000000000000000dead"
    unlisted = "0x000000000000000000000000000000000000beef"
    blacklist.add(listed)

    assert listed in blacklist
    assert unlisted not in blacklist
