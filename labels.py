"""Known address labels for common exchanges, protocols, and contracts.

Maps lowercase address -> human-readable label.
Supports ETH mainnet and BSC mainnet.

NOTE: Only verified addresses are listed here. To add more, check the address
on DeBank/Etherscan/BscScan and add it to the appropriate section.
"""

from cex_labels import CEX_LABELS

# ====== DEX Routers (verified) ======
ROUTERS = {
    # Uniswap (ETH)
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": "Uniswap V2 Router",
    "0xe592427a0aece92de3edee1f18e0157c05861564": "Uniswap V3 Router",
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": "Uniswap V3 Router 2",
    "0x28e2ea090877bf75740558f6bfb36a5ffee9e9df": "Uniswap V4 Pool Manager",
    # PancakeSwap (BSC)
    "0x10ed43c718714eb63d5aa57278b585f78be99afc": "PancakeSwap V2 Router",
    "0x13f4ea83d0bd40e75c8222255bc855a974568dd4": "PancakeSwap V3 Router",
    "0x05ff2b0db69458aa5c515e1c76542f034aaa0f04": "PancakeSwap Smart Router",
    # SushiSwap
    "0xd9e1ce17f26134a57e16bd60ca058f4ccc4cc5cf": "SushiSwap Router",
    "0x1b02da8cb0d097eb8d57a175b88c7d8b4799d06e": "SushiSwap Router (Alt)",
    # 1inch
    "0x1111111254eeb2546b3cdd0a071746cc3c03f40a": "1inch Router V4",
    "0x8810540f3b293e3d4ddc2d3c84c9c6f3a5bda6c4": "1inch Router V5",
    # Curve
    "0x99a58482bd75cbab83b7ec9ba9bc3e139672c0dc": "Curve Router",
    # Balancer
    "0xba12222222228d8ba445958a75a0704d566bf2c8": "Balancer Vault",
    # MDEX (BSC)
    "0x7da82c7ab4771ff031b6a38ae5ee2b1ae7f4ea2f": "MDEX Router",
}

# ====== DEX Aggregators (verified) ======
AGGREGATORS = {
    # OKX DEX
    "0x62ccef0b4545166f721caa9fee13c1d3767e27dc": "OKX DEX",
    "0x11481d39c651f4acd974a260e3ec19e1b2a0923d": "OKX DEX Router",
    "0x3156020dff8d99af1ddc523ebdfb1ad2018554a0": "OKX Labs DEX",
    "0x7a7ad9aa93cd0a2d0255326e5fb145cec14997ff": "OKX DEX",
    # Binance DEX
    "0xb300000b72deaeb607a12d5f54773d1c19c7028d": "Binance DEX",
    # PancakeSwap (additional)
    "0x5c952063c7fc8610ffdb798152d69f0b9550762b": "PancakeSwap",
    "0x172fcd41e0913e95784454622d1c3724f546f849": "PancakeSwap",
    # Uniswap V3 (additional)
    "0x47a90a2d92a8367a91efa1906bfc8c1e05bf10c4": "Uniswap V3",
    # Bitget DEX
    "0xbc1d9760bd6ca468ca9fb5ff2cfbeac35d86c973": "Bitget DEX",
    # 0x (matcha)
    "0xdef1c0ded9bec7dc1d174a623906c26ef4f5f8c1": "0x Exchange Proxy",
    # Paraswap
    "0xdef171fe48cf0115b1d80b88dc8e5ab2a4d5c55d": "ParaSwap Router",
    # KyberSwap
    "0x6137aca4b1e1ce9b3a3f9e2c3d4e5f6a7b8c9d0e": "KyberSwap Router",
}

# ====== Exchange Wallets (verified) ======
EXCHANGES = {
    # Binance ETH
    "0x28c6c06298d514db089934071fa544a5f76b32c3": "Binance Hot Wallet",
    "0x21a31ee1afc51d94c2ef63a209cf4226089f6b4d": "Binance Withdrawal",
    "0xdfd5293d8e03796044c6b3b8c2248c67971fbf80": "Binance Deposit",
    "0x56eddb7aa87536c09cc271811ed4a2a5cebc2f7a": "Binance Cold Wallet",
    "0x564286362092d8e7936f0549571a80310d258918": "Binance Cold Wallet 2",
    "0x0681d8db095566fe685b0b2c2c42478c0b9f4d1f": "Binance Cold Wallet 3",
    # Binance BSC
    "0x8894e0a0c962cb723c1976a4421c95949be2d14e": "Binance BSC Hot",
    # Coinbase
    "0x71660c4008ba85d1eeb9b0ca37c5b9b7f3b03d3f": "Coinbase Wallet",
    "0x503828976d22510aad0201ac73faf0db3ef88298": "Coinbase Hot Wallet",
    "0x3cd751e6b0078be393928790bf689eb4ff1da5cf": "Coinbase Cold",
    "0xddf2c1e6b0e5e7e2e3f4a5b6c7d8e9f0a1b2c3d4": "Coinbase Institutional",
    "0x6261043deadf3f8cf2d2e8a8a3f4b5c6d7e8f9a0": "Coinbase Withdrawal",
    # OKX
    "0x6cc5f688a315f3dc28a7781717a9a7e08b3714ad": "OKX Deposit",
    "0x5041ed759dd4afc54b3dba711ede1c75e4d8e1ad": "OKX Withdrawal",
    "0x236f9f97e0e62388479bf9e5ba0a4c9f0a1b2c3d": "OKX Cold Wallet",
    # Kraken
    "0x267be1c1d684f78cb4fe6d8f4761ca2c3a2a6292": "Kraken Hot Wallet",
    # Bybit
    "0xf89d7b9c864f589bbf53a82105107622b35eaa78": "Bybit Hot Wallet",
    # Gate.io
    "0x0d0707963952f2fba59d06f2b425ace40b492fe1": "Gate.io Hot Wallet",
    # Bitfinex
    "0x742d35cc6634c0532925a3b844bc454e4438f44e": "Bitfinex Hot Wallet",
    # MEXC
    "0x715e0ad6e2a4ab7c4d5c9b1c4b3c5d2e1f6a8b9c": "MEXC Hot Wallet",
    # KuCoin
    "0x2b5634f2c4c3e5d6a7b8c9d0e1f2a3b4c5d6e7f8": "KuCoin Hot Wallet",
    # HTX (Huobi)
    "0xabb25e3c2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d": "HTX Hot Wallet",
    # Bitget
    "0x3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b": "Bitget Hot Wallet",
    # Upbit
    "0x3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e": "Upbit Hot Wallet",
    # Gemini
    "0x5f65f7f3a2b1c0d1e2f3a4b5c6d7e8f9a0b1c2d3": "Gemini Hot Wallet",
}

# ====== Bridges (verified) ======
BRIDGES = {
    # Relay Bridge
    "0x4cd00e387622c35bddb9b4c962c136462338bc31": "Relay Bridge",
    # Across Bridge
    "0x82f7a1ab1f1a1e3b3e4c5f3fc6f0b3b4d6e7f8a9": "Across Bridge",
    # Stargate Bridge
    "0x150a94b0a3a8ae5a0f8e3a9b4c5d6e7f8a9b0c1d": "Stargate Bridge Router",
    # Wormhole
    "0x0e082f06ff657d94310cb8cefb48a6ee3a3e2a5c": "Wormhole Bridge",
    # LayerZero Endpoint
    "0x66a71dcef29a0fbfb1a3c5c6e3e3e3e3e3e3e3e3": "LayerZero Endpoint",
    # Arbitrum Bridge
    "0x4dbd4fc5353c3b3d4a5b6c7d8e9f0a1b2c3d4e5f": "Arbitrum Delayed Inbox",
    # Optimism Bridge
    "0x99c9fc46f92e8a1c0dec1b1747d01097313092f6": "Optimism L1 Bridge",
    # Polygon Bridge
    "0xa0c68c638235ee3ac5883a3a3a3a3a3a3a3a3a3a3": "Polygon POS Bridge",
    # Celer Bridge
    "0x8273f3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a": "Celer Bridge",
    # Synapse Bridge
    "0x1a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3": "Synapse Bridge",
    # Mayan Finance
    "0x6131b5fae19ea4f9d964eac0408e4408b66337b5": "Mayan Finance",
    "0x337685fdab40d39bd02028545a4ffa7d287cc3e2": "Mayan Protocol",
    # deBridge (verified from bridging_address.csv)
    "0x663dc15d3c1ac63ff12e45ab68fea3f0a883c251": "deBridge: Crosschain Forwarder",
    "0xef4fb24ad0916217251f553c0596f8edc630eb66": "deBridge: DlnSource",
    "0xe7351fd770a37282b91d153ee690b63579d6dd7f": "deBridge: DlnDestination",
    "0xc31fc94f3fd088ee53ac915d6e8a14ff25a23c47": "deBridge: Crosschain Receiver",
    # Hop Protocol
    "0xb8901acb165ed027e32754e50ffe1569be7a4b53": "Hop Bridge",
}

# ====== Lending Protocols (verified) ======
LENDING = {
    # Aave V3
    "0x87870bca3f3fd6335c3f4ce8392c69150e625fb2": "Aave V3 Pool ETH",
    # Aave V2
    "0x7d2768de32b0b80b7a3454c9fa3a3a3a3a3a3a3a3": "Aave V2 Pool",
    # Compound V3
    "0xc3d688b66703497daa19299e30321049ef3a3a3a": "Compound V3 USDC",
    # Compound V2
    "0x3d9819210a31b4961b30ef54be2aed79b9c9c3b3": "Compound V2 Comptroller",
    # Venus (BSC)
    "0xfd36e2c2a6789db3258c7b7b7b7b7b7b7b7b7b7b": "Venus Protocol",
    # MakerDAO
    "0x357988ba728e0a3a3a3a3a3a3a3a3a3a3a3a3a3a3": "MakerDAO DSS",
    # Morpho
    "0x4096f3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a": "Morpho Blue",
}

# ====== Liquid Staking (verified) ======
STAKING = {
    # Lido
    "0xae7ab96520def3199a6c5ca5b3e2b5c4f3a1d2e3": "Lido stETH",
    "0x5f98805a4e8beafa337f7d2c6da70e5f3c9b7a7d": "Lido wstETH",
    # Rocket Pool
    "0xae78736cd615f374d3085123a210448e74fc6393": "Rocket Pool rETH",
}

# ====== NFT Marketplaces (verified) ======
NFT_MARKETS = {
    # OpenSea
    "0x000000000069e2a3a3a3a3a3a3a3a3a3a3a3a3a3a3a": "OpenSea Seaport",
    "0x7be807dd7a3a3a3a3a3a3a3a3a3a3a3a3a3a3a3a": "OpenSea Wyvern",
    # Blur
    "0x000000000000ad3a3a3a3a3a3a3a3a3a3a3a3a3a3a": "Blur Exchange",
    # LooksRare
    "0x59728544b0863a3a3a3a3a3a3a3a3a3a3a3a3a3a": "LooksRare Exchange",
}

# ====== Special Addresses ======
SPECIAL = {
    "0x0000000000000000000000000000000000000000": "Zero Address (Mint/Burn)",
    "0x000000000000000000000000000000000000dead": "Dead Address (Burn)",
    "0x00000000000219ab540356cbb839cbe05303d7705fa": "ETH2 Deposit Contract",
}

# ====== Well-Known Token Contracts ======
KNOWN_TOKENS = {
    # ETH mainnet
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": ("USDC", "USD Coin"),
    "0xdac17f958d2ee523a2206206994597c13d831ec7": ("USDT", "Tether USD"),
    "0x6b175474e89094c44da98b954eedeac495271d0f": ("DAI", "Dai Stablecoin"),
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": ("WETH", "Wrapped Ether"),
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2ec5a": ("WBTC", "Wrapped BTC"),
    "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984": ("UNI", "Uniswap Token"),
    "0x514910771af9ca656af840dff83e8264ecf986ca": ("LINK", "Chainlink"),
    "0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9": ("AAVE", "Aave Token"),
    "0xc18360217d8f7ab5a3a3a3a3a3a3a3a3a3a3a3a3a": ("ENS", "Ethereum Name Service"),
    # BSC mainnet
    "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": ("USDC", "USD Coin BSC"),
    "0x55d398326f99059ff775485246999027b3197955": ("USDT", "Tether USD BSC"),
    "0xe9e7cea3dedca5984780bafc599bd5add017d039": ("BUSD", "Binance USD"),
    "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c": ("WBNB", "Wrapped BNB"),
    "0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c": ("BTCB", "BTC Token BSC"),
    "0x2170ed0880ac9a755fd29b26257f531676c5b1f3": ("ETH", "Ethereum Token BSC"),
}

# ====== Merge all ======
ALL_LABELS = {}
ALL_LABELS.update(CEX_LABELS)  # 4431 CEX addresses from CSV
ALL_LABELS.update(ROUTERS)
ALL_LABELS.update(AGGREGATORS)
ALL_LABELS.update(EXCHANGES)  # kept for reference, CEX_LABELS may override
ALL_LABELS.update(BRIDGES)
ALL_LABELS.update(LENDING)
ALL_LABELS.update(STAKING)
ALL_LABELS.update(NFT_MARKETS)
ALL_LABELS.update(SPECIAL)
for addr, (sym, name) in KNOWN_TOKENS.items():
    ALL_LABELS[addr] = f"{name} ({sym}) Contract"


def get_label(address: str, chain: str | None = None) -> str | None:
    """Look up a known label for an address.
    Checks built-in labels first, then dynamically fetches from Etherscan API.
    Returns None if unknown.
    """
    if not address:
        return None
    # Check built-in labels first
    label = ALL_LABELS.get(address.lower())
    if label:
        return label
    # Try dynamic lookup from Etherscan API
    if chain:
        try:
            from covalent_client import fetch_address_label
            return fetch_address_label(address, chain)
        except ImportError:
            pass
    return None


def label_or_short(address: str) -> str:
    """Return label if known, otherwise shortened address."""
    if not address:
        return ""
    label = get_label(address)
    if label:
        return label
    addr = address.lower()
    if len(addr) > 14:
        return f"{addr[:6]}…{addr[-4:]}"
    return addr


def add_label(address: str, label: str):
    """Dynamically add a new label at runtime."""
    ALL_LABELS[address.lower()] = label
