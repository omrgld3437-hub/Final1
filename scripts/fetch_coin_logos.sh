#!/bin/bash
# Trust Wallet asset repo'dan projede kullanılan coin logolarını ui/assets/coins/ altına indirir.
# Kaynak: https://github.com/trustwallet/assets (MIT)
set -e
BASE="https://raw.githubusercontent.com/trustwallet/assets/master"
COINS_DIR="$(dirname "$0")/../ui/assets/coins"
mkdir -p "$COINS_DIR"

fetch() {
  local sym="$1"
  local rel="$2"
  local out="$COINS_DIR/${sym}.png"
  echo "Fetching $sym -> $out"
  curl -sfL "$BASE/$rel" -o "$out" || echo "  (skip $sym - fetch failed)"
}

fetch "BTC" "blockchains/bitcoin/info/logo.png"
fetch "ETH" "blockchains/ethereum/info/logo.png"
fetch "BNB" "blockchains/binance/info/logo.png"
fetch "XRP" "blockchains/ripple/info/logo.png"
fetch "ADA" "blockchains/cardano/info/logo.png"
fetch "SOL" "blockchains/solana/info/logo.png"
fetch "DOT" "blockchains/polkadot/info/logo.png"
fetch "LTC" "blockchains/litecoin/info/logo.png"
fetch "DOGE" "blockchains/doge/info/logo.png"
fetch "AVAX" "blockchains/avalanchec/info/logo.png"
fetch "USDT" "blockchains/ethereum/assets/0xdAC17F958D2ee523a2206206994597C13D831ec7/logo.png"
fetch "USDC" "blockchains/ethereum/assets/0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48/logo.png"
fetch "LINK" "blockchains/ethereum/assets/0x514910771AF9Ca656af840dff83E8264EcF986CA/logo.png"
fetch "BUSD" "blockchains/ethereum/assets/0x4Fabb145d64652a948d72533023f6E7A623C7C53/logo.png"
fetch "FDUSD" "blockchains/ethereum/assets/0xc5f0f7b66764F6ec8C8Dff7BA683102295E16409/logo.png"
fetch "LUNA" "blockchains/terra/info/logo.png"
fetch "SHIB" "blockchains/ethereum/assets/0x95aD61b0a150d79219dC64aF0d4B5B3c6dDdE9c0/logo.png"

echo "Done. Logos in $COINS_DIR"
ls -la "$COINS_DIR"/*.png 2>/dev/null || true
