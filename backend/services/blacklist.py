# blacklist.py
# Use lowercase for consistent normalization
BLACKLIST = {
    # Ronin / Axie Infinity - Lazarus Group (Mar 2022)
    "0x098b716b8aaf21512996dc57eb0615e2383e2f96",
    # Euler Finance (Mar 2023)
    "0xb66cd966670d962c227b3eaba30a872dbfb995db",
    "0x5f259d0b76665c337c6104145894f4d1d2758b8c",
    # Wormhole Bridge (Feb 2022)
    "0x629e7da20197a5429d30da36e77d06cdf796b71a",
    # Abracadabra Rekt III (Oct 2025)
    "0x1aade3e9062d124b7deb0ed6ddc7055efa7354d",
    "0x1ff8ea9b29aa10713774b60134d53529301ca9c5",
    "0xb8e0a4758df2954063ca4ba3d094f2d6eda9b993",
    # Beanstalk Farms flash loan (Apr 2022)
    "0x1c5dcdd006ea78a7e4783f9e6021c32935a10fb4",
    # Nomad Bridge (Aug 2022)
    "0xb5c55f76f90cc528b2609109ca14d8d84593590e",
    # Wasabi Protocol (May 2026)
    "0xcd77423f1bfa362c43f98356360c1f6c6e5fe989f18036e874884e9ad4a70116",
    # Venus Protocol (Mar 2026)
    "0x1a35bd28efd46cfc46c2136f878777d69ae16231",
    # ResupplyFi (June 2025)
    "0x6d9f6e900ac2ce6770fd9f04f98b7b0fc355e2ea",
}


EXPLOIT_TARGETS = {
    # Euler Finance eDAI contract targeted in the Mar 2023 exploit path.
    "0x27182842e098f60e3d576794a5bffb0777e025d3",
}
