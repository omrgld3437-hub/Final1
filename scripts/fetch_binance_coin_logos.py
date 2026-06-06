#!/usr/bin/env python3
"""
Binance'de listeli (USDT pair) tüm coinlerin logolarını Trust Wallet assets
repo'dan indirip ui/assets/coins/ altına kaydeder.
Kaynak: https://github.com/trustwallet/assets (MIT)
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

BINANCE_EXCHANGE_INFO = "https://api.binance.com/api/v3/exchangeInfo"
GITHUB_RAW = "https://raw.githubusercontent.com/trustwallet/assets/master"
GITHUB_API_BLOCKCHAINS = "https://api.github.com/repos/trustwallet/assets/contents/blockchains"
REQUEST_TIMEOUT = 60
REQUEST_DELAY = 0.15  # GitHub rate limit

# coinLogo.js ile uyumlu: Binance symbol -> logo dosya adı (tek sembol)
NORMALIZE_SYMBOL = {
    "XBT": "BTC",
    "LUNA2": "LUNA",
    "1000SHIB": "SHIB",
    "1000PEPE": "PEPE",
    "1000FLOKI": "FLOKI",
    "1000LUNC": "LUNC",
    "1000BONK": "BONK",
    "1000RATS": "RATS",
    "1000SATS": "SATS",
}

# Native chain logoları (symbol -> blockchains/xxx/info/logo.png) - API çağrısı yapmamak için statik
NATIVE_CHAIN_PATHS = {
    "BTC": "blockchains/bitcoin/info/logo.png",
    "ETH": "blockchains/ethereum/info/logo.png",
    "BNB": "blockchains/binance/info/logo.png",
    "XRP": "blockchains/ripple/info/logo.png",
    "ADA": "blockchains/cardano/info/logo.png",
    "SOL": "blockchains/solana/info/logo.png",
    "DOT": "blockchains/polkadot/info/logo.png",
    "LTC": "blockchains/litecoin/info/logo.png",
    "DOGE": "blockchains/doge/info/logo.png",
    "AVAX": "blockchains/avalanchec/info/logo.png",
    "LUNA": "blockchains/terra/info/logo.png",
    "LUNC": "blockchains/terrav2/info/logo.png",
    "MATIC": "blockchains/polygon/info/logo.png",
    "LINK": "blockchains/ethereum/assets/0x514910771AF9Ca656af840dff83E8264EcF986CA/logo.png",
    "BCH": "blockchains/bitcoincash/info/logo.png",
    "XLM": "blockchains/stellar/info/logo.png",
    "ALGO": "blockchains/algorand/info/logo.png",
    "VET": "blockchains/vechain/info/logo.png",
    "ICP": "blockchains/internet_computer/info/logo.png",
    "FIL": "blockchains/filecoin/info/logo.png",
    "TRX": "blockchains/tron/info/logo.png",
    "ETC": "blockchains/classic/info/logo.png",
    "TON": "blockchains/ton/info/logo.png",
    "HBAR": "blockchains/hedera/info/logo.png",
    "APT": "blockchains/aptos/info/logo.png",
    "NEAR": "blockchains/near/info/logo.png",
    "INJ": "blockchains/nativeinjective/info/logo.png",
    "SUI": "blockchains/sui/info/logo.png",
    "SEI": "blockchains/sei/info/logo.png",
    "RUNE": "blockchains/thorchain/info/logo.png",
    "ATOM": "blockchains/cosmos/info/logo.png",
    "FTM": "blockchains/fantom/info/logo.png",
    "XTZ": "blockchains/tezos/info/logo.png",
    "EGLD": "blockchains/elrond/info/logo.png",
    "KAVA": "blockchains/kava/info/logo.png",
    "ZEC": "blockchains/zcash/info/logo.png",
    "XMR": "blockchains/monero/info/logo.png",
    "DASH": "blockchains/dash/info/logo.png",
    "WAVES": "blockchains/waves/info/logo.png",
    "KSM": "blockchains/kusama/info/logo.png",
    "ONE": "blockchains/harmony/info/logo.png",
    "CELO": "blockchains/celo/info/logo.png",
    "ZIL": "blockchains/zilliqa/info/logo.png",
    "QTUM": "blockchains/qtum/info/logo.png",
    "ICX": "blockchains/icon/info/logo.png",
    "ZEN": "blockchains/zen/info/logo.png",
    "RVN": "blockchains/ravencoin/info/logo.png",
    "SC": "blockchains/siacoin/info/logo.png",
    "DGB": "blockchains/digibyte/info/logo.png",
    "LSK": "blockchains/lisk/info/logo.png",
    "ONT": "blockchains/ontology/info/logo.png",
    "DCR": "blockchains/decred/info/logo.png",
    "NANO": "blockchains/nano/info/logo.png",
    "STEEM": "blockchains/steem/info/logo.png",
    "DENT": "blockchains/ethereum/assets/0x3597bfD533a99c9aa083587B074434E61Eb0A258/logo.png",
    "SAND": "blockchains/ethereum/assets/0x3845badAde8e6dFF049820680d1F14bD3903a5d0/logo.png",
    "MANA": "blockchains/ethereum/assets/0x0F5D2fB29fb7d3CFeE444a200298f468908cC942/logo.png",
    "AXS": "blockchains/ethereum/assets/0xBB0E17EF65F82Ab018d8EDd776e8DD940327B28b/logo.png",
    "ENJ": "blockchains/ethereum/assets/0xF629cBd94d3791C9250152BD8dfBDF380E2a3B9c/logo.png",
    "CHZ": "blockchains/ethereum/assets/0x3506424F91fD33084466F402d5D97f05F8e3b4AF/logo.png",
    "THETA": "blockchains/theta/info/logo.png",
    "GRT": "blockchains/ethereum/assets/0xC944E90C64B2c07662A292be6244BDF05cda44a7/logo.png",
    "BAT": "blockchains/ethereum/assets/0x0D8775F648430679A709E98d2b0Cb6250d2887EF/logo.png",
    "SNX": "blockchains/ethereum/assets/0xC011a73ee8576Fb46F5E1c5751cA3B9Fe0af2a6F/logo.png",
    "KNC": "blockchains/ethereum/assets/0xdd974D5C2e2928deA5F71b9825b8b646686BD200/logo.png",
    "1INCH": "blockchains/ethereum/assets/0x111111111117dC0aa78b770fA6A738034120C302/logo.png",
    "OCEAN": "blockchains/ethereum/assets/0x967da4048cD07a37837AfE2922c7Db9cCd6E8E8a/logo.png",
    "CELR": "blockchains/ethereum/assets/0x4F9254C83EB84f1a232D73fdDf583a5e2d35c7b0/logo.png",
    "SKL": "blockchains/ethereum/assets/0x00c83aeCC790e8a4453e5dD3B0B4b3680501a7A7/logo.png",
    "ZRX": "blockchains/ethereum/assets/0xE41d2489571d322189246DaFA5ebDe1F4699F498/logo.png",
    "IMX": "blockchains/ethereum/assets/0xF57e7e7C23978C3cAEC3C3548E3D615c346e79fF/logo.png",
    "BLZ": "blockchains/ethereum/assets/0x5732046A883704404F284Ce41FfAD5fd2FfF0632/logo.png",
    "ASTR": "blockchains/astar/info/logo.png",
    "MOVR": "blockchains/moonriver/info/logo.png",
    "GLMR": "blockchains/moonbeam/info/logo.png",
    "DYDX": "blockchains/ethereum/assets/0x92D6C1e31e14520e676a687F0a93788B716BEff5/logo.png",
    "ROSE": "blockchains/oasis/info/logo.png",
    "KDA": "blockchains/kadena/info/logo.png",
    "FLOW": "blockchains/flow/info/logo.png",
    "AUDIO": "blockchains/ethereum/assets/0x18aAA7115705e8be94bfFEBDE57Af9BFc265B998/logo.png",
    "GALA": "blockchains/ethereum/assets/0xd1d2Eb1B1e90B638588728b4130137D262C87cae/logo.png",
    "GMT": "blockchains/ethereum/assets/0xe3c408BD53c31C085a1746af401A4042954ff8f8/logo.png",
    "STORJ": "blockchains/ethereum/assets/0xB64ef51C888972c908CFacf59B47C1AfBC0Ab8aC/logo.png",
    "API3": "blockchains/ethereum/assets/0x0b38210ea11411557c13457D4dA7dC6ea731B88a/logo.png",
    "LRC": "blockchains/ethereum/assets/0xBBbbCA6A901c926F240b89EacB641d8Aec7AEafD/logo.png",
    "ANKR": "blockchains/ethereum/assets/0x8290333ceF9e6D528dD5618Fb97a76f268f3EDD4/logo.png",
    "FET": "blockchains/fetch/info/logo.png",
    "AGIX": "blockchains/ethereum/assets/0x5B7533812759B45C2B44C19e320ba2cD2681b542/logo.png",
    "RNDR": "blockchains/ethereum/assets/0x6De037ef9aD2725EB40118Bb1702EBb27e4Aeb24/logo.png",
    "RENDER": "blockchains/ethereum/assets/0x6De037ef9aD2725EB40118Bb1702EBb27e4Aeb24/logo.png",
    "JASMY": "blockchains/ethereum/assets/0x7420B4b9a0110cdC71fB720908340C03F9Bc03EC/logo.png",
    "ARKM": "blockchains/ethereum/assets/0x6E2a43be0B1d33b726f0CA3b8c83b34E498e5Ed7/logo.png",
    "WLD": "blockchains/ethereum/assets/0x163f8C2467924be0ae7B5347228CABF260318753/logo.png",
    "STRK": "blockchains/starknet/info/logo.png",
    "PENDLE": "blockchains/ethereum/assets/0x808507121B80c02388fAd14726482e061B8da827/logo.png",
    "ENS": "blockchains/ethereum/assets/0xC18360217D8F7Ab5e7c516566761Ea12Ce7F9D72/logo.png",
    "CFX": "blockchains/conflux/info/logo.png",
    "STX": "blockchains/bitcoin/assets/bad3c2e1347512d3c363269a8d022675e7b00444518d56c5e2b3ad1c5d68e7a7d/logo.png",
}

# Token'lar (symbol -> path); native ile çakışanlar üzerine yazılır
TOKEN_PATHS = {
    "USDT": "blockchains/ethereum/assets/0xdAC17F958D2ee523a2206206994597C13D831ec7/logo.png",
    "USDC": "blockchains/ethereum/assets/0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48/logo.png",
    "BUSD": "blockchains/ethereum/assets/0x4Fabb145d64652a948d72533023f6E7A623C7C53/logo.png",
    "FDUSD": "blockchains/ethereum/assets/0xc5f0f7b66764F6ec8C8Dff7BA683102295E16409/logo.png",
    "LINK": "blockchains/ethereum/assets/0x514910771AF9Ca656af840dff83E8264EcF986CA/logo.png",
    "SHIB": "blockchains/ethereum/assets/0x95aD61b0a150d79219dC64aF0d4B5B3c6dDdE9c0/logo.png",
    "UNI": "blockchains/ethereum/assets/0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984/logo.png",
    "AAVE": "blockchains/ethereum/assets/0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9/logo.png",
    "MKR": "blockchains/ethereum/assets/0x9f8F72aA9304c8B593d555F12eF6589cC3A579A2/logo.png",
    "CRV": "blockchains/ethereum/assets/0xD533a949740bb3306d119CC777fa900bA034cd52/logo.png",
    "SUSHI": "blockchains/ethereum/assets/0x6B3595068778DD592e39A122f4f5a5cF09C90fE2/logo.png",
    "COMP": "blockchains/ethereum/assets/0xc00e94Cb662C3520282E6f5717214004A7f26888/logo.png",
    "YFI": "blockchains/ethereum/assets/0x0bc529c00C6401aEF6D220BE8C6Ea1667F6Ad93e/logo.png",
    "WBTC": "blockchains/ethereum/assets/0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599/logo.png",
    "DAI": "blockchains/ethereum/assets/0x6B175474E89094C44Da98b954EedeAC495271d0F/logo.png",
    "TUSD": "blockchains/ethereum/assets/0x0000000000085d4780B73119b644AE5ecd22b376/logo.png",
    "USDP": "blockchains/ethereum/assets/0x8E870D67F660D95d5be530380D0eC0bd388289E1/logo.png",
    "FRAX": "blockchains/ethereum/assets/0x853d955aCEf822Db058eb8505911ED77F175b99e/logo.png",
    "PYUSD": "blockchains/ethereum/assets/0x6c3ea9036406852006290770BEdFcAbA0e23A0e8/logo.png",
    "LDO": "blockchains/ethereum/assets/0x5A98FcBEA516Cf06857215779Fd812CA3beF1B32/logo.png",
    "ARB": "blockchains/ethereum/assets/0xB50721BCf8d664c30412Cfbc6cf7a15145234ad1/logo.png",
    "OP": "blockchains/ethereum/assets/0x4200000000000000000000000000000000000042/logo.png",
    "PEPE": "blockchains/ethereum/assets/0x6982508145454Ce325dDbE47a25d4ec3d2311933/logo.png",
    "FLOKI": "blockchains/ethereum/assets/0xcf0C122c6b73ff809C693DB761e7BaeBe62b6a2E/logo.png",
    "BONK": "blockchains/solana/assets/DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263/logo.png",
    "WIF": "blockchains/solana/assets/EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm/logo.png",
    "JUP": "blockchains/solana/assets/JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN/logo.png",
}


def normalize_symbol(symbol: str) -> str:
    """Binance base symbol -> tek logo anahtarı (coinLogo.js ile uyumlu)."""
    s = (symbol or "").strip().upper()
    return NORMALIZE_SYMBOL.get(s, s)


def get_binance_base_symbols(session: requests.Session) -> list[str]:
    """Binance exchangeInfo'dan TRADING USDT pair'lerinin base symbol listesi."""
    r = session.get(BINANCE_EXCHANGE_INFO, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    symbols = []
    for s in data.get("symbols", []):
        if s.get("status") != "TRADING":
            continue
        sym = s.get("symbol", "")
        if sym.endswith("USDT"):
            base = sym[:-4]
            if base and base not in symbols:
                symbols.append(base)
    return sorted(symbols)


def build_symbol_to_path(_session: requests.Session) -> dict[str, str]:
    """Statik native + token map -> symbol -> relative path (API çağrısı yok)."""
    out = dict(NATIVE_CHAIN_PATHS)
    out.update(TOKEN_PATHS)
    return out


def download_logo(session: requests.Session, path: str, out_path: Path) -> bool:
    """Tek logo indirir. Başarılıysa True."""
    url = f"{GITHUB_RAW}/{path}"
    try:
        r = session.get(url, timeout=20)
        if r.status_code != 200 or len(r.content) < 100:
            return False
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(r.content)
        return True
    except Exception:
        return False


def main() -> int:
    base_dir = Path(__file__).resolve().parent.parent
    coins_dir = base_dir / "ui" / "assets" / "coins"
    coins_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.setdefault("User-Agent", "BinanceCoinLogos/1.0")

    print("Fetching Binance USDT symbols...")
    base_symbols = get_binance_base_symbols(session)
    print(f"Found {len(base_symbols)} base symbols.")

    print("Building symbol -> Trust Wallet path map...")
    symbol_to_path = build_symbol_to_path(session)
    print(f"Map has {len(symbol_to_path)} entries.")

    ok = 0
    skip = 0
    fail = 0
    for base in base_symbols:
        key = normalize_symbol(base)
        path = symbol_to_path.get(key)
        out_file = coins_dir / f"{key}.png"
        if out_file.exists() and path:
            skip += 1
            continue
        if not path:
            fail += 1
            continue
        time.sleep(REQUEST_DELAY)
        if download_logo(session, path, out_file):
            ok += 1
            if ok <= 50 or ok % 100 == 0:
                print(f"  OK {key}")
        else:
            fail += 1

    # Stabil coin logoları (uygulamada kullanılanlar) Binance'de olmasa bile indir
    STABLECOINS = ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI", "FRAX", "PYUSD")
    for key in STABLECOINS:
        path = symbol_to_path.get(key)
        out_file = coins_dir / f"{key}.png"
        if out_file.exists() or not path:
            continue
        time.sleep(REQUEST_DELAY)
        if download_logo(session, path, out_file):
            ok += 1
            print(f"  OK (stable) {key}")
        else:
            fail += 1

    print(f"Done: {ok} downloaded, {skip} already existed, {fail} missing/failed.")
    return 0 if fail <= len(base_symbols) else 1


if __name__ == "__main__":
    sys.exit(main())
