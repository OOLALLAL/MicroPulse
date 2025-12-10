# MicroPulse  
A lightweight real-time microstructure engine for monitoring short-horizon order flow signals on Binance Futures (BTCUSDT).

## Overview
MicroPulse processes Level-2 depth and trade streams at high frequency and extracts short-term microstructure metrics such as:
- Mid-price movements  
- Order Book Imbalance (OBI)  
- Cumulative Volume Delta (CVD)  
- Local price spikes  
- Liquidity wall creation/removal  
- Short-window trade statistics  

The current version logs signals, generates position entries/exits, and records transactions for offline analysis.

## Key Concepts
### Order Book Features
- **Mid-price tracking** using top-of-book quotes  
- **OBI** (bid–ask liquidity imbalance)  
- **Liquidity wall detection** based on relative size vs. average book depth  
- **Wall removal events** used as potential momentum triggers  

### Trade Features
- **CVD / window CVD** (buy vs sell pressure)  
- **Trade frequency (TPS)**  
- **Average trade size**  

### Signal Logic (Current)
A position is opened when:
- A liquidity wall is removed within a short window  
- Price spike + OBI alignment support the direction  
- Trade acceleration conditions are met  

A position is closed based on:
- TP/SL  
- Reversal in microstructure flow (CVD/OBI)  
- Time-based stop  
- Early invalidation (fast adverse move)

## Usage
```
python micropulse.py
```

The script connects to:

```
wss://fstream.binance.com/stream?streams=btcusdt@depth5@100ms/btcusdt@trade
```

And prints real-time metrics such as:

```
mid=102345.23, obi=0.182, spk_up=0.0012, buy10s=23.2, sell10s=11.8, cvd=12.4, removed_wall={...}
```

Transactions are automatically appended to:

```
transaction.csv
```

## File Structure
```
micropulse.py       # main engine (orderflow features + signal logic)
transaction.csv     # auto-generated trade log
```

## Requirements
```
pip install pandas websocket-client
```

## Notes
- The engine is modular: entry/exit logic can be replaced without touching the feature extraction.
- This version focuses on metric extraction and basic rule-based signals.
- Future extensions may include: backtesting module, strategy evaluation, execution simulator.

