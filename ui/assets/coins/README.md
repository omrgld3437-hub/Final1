# Coin logoları (Trust Wallet lokal)

Bu klasörde coin logoları `{SYMBOL}.png` adıyla bulunur.

- Örnek: `BTC.png`, `ETH.png`, `USDT.png`, `XRP.png`
- Kaynak: Trust Wallet assets – https://github.com/trustwallet/assets (MIT)
- URL: `/ui/assets/coins/BTC.png` (static olarak sunulur).

**Logoları toplu indirmek için (Binance’de listeli tüm USDT coinler):**
```bash
python3 scripts/fetch_binance_coin_logos.py
```
Binance exchangeInfo’dan sembolleri alır, Trust Wallet repo’dan eşleşen logoları indirir. Eşleşmeyen coinlerde UI initials fallback kullanır.

**Sadece temel birkaç coin için:**
```bash
./scripts/fetch_coin_logos.sh
```
Yeni coin eklemek için Python script’teki `NATIVE_CHAIN_PATHS` veya `TOKEN_PATHS` sözlüğüne `"SYMBOL": "blockchains/.../logo.png"` ekleyebilirsin.
