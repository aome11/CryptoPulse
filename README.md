# CryptoPulseBot 🚀

**CryptoPulseBot** is a high-performance, asynchronous Telegram bot built with Python for real-time cryptocurrency price monitoring. The bot integrates seamlessly with the public **Binance API**, allowing users to subscribe to top digital assets and receive instant background alerts whenever market prices fluctuate.

This project serves as a production-ready demonstration of asynchronous data fetching (`asyncio` / `aiohttp`), background workers, and clean relational database management without the risk of IP bans or rate-limiting issues.

🤖 **Test the live bot in Telegram:** [t.me/YOUR_BOT_USERNAME](https://t.me)

---

## 🛠 Tech Stack
*   **Language:** Python 3.10+
*   **Bot Framework:** `aiogram 3.x` (Modern, fully asynchronous Telegram Bot framework)
*   **API Client:** `aiohttp` (Asynchronous HTTP requests to fetch live exchange rates)
*   **Database:** `aiosqlite` (Asynchronous SQLite3 wrapper to handle user subscriptions)
*   **Environment Management:** `python-dotenv` (Secure environment variable configuration via `.env`)

---

## 🔥 Core Features
1.  **Asynchronous Background Worker:** Features a non-blocking background loop (`asyncio task`) that checks Binance price tickers every 10 minutes without freezing the main bot interactions.
2.  **Top Asset Coverage:** Out-of-the-box stable parsing and price tracking for:
    *   `BTC` (Bitcoin)
    *   `ETH` (Ethereum)
    *   `TON` (Toncoin)
3.  **Relational Storage:** Auto-initializes a clean SQLite database to manage user subscription states and persistently track the `last_seen_price`.
4.  **Smart Rate Limiting:** Implements built-in micro-delays between API calls to strictly respect Binance's server connection guidelines and avoid network request drops.

---

## 📋 Bot Commands
*   `/start` — Welcomes the user and prints clear setup instructions.
*   `/add [TICKER]` — Adds a specific ticker to the user's tracking list (e.g., `/add TONUSDT`).
*   `/list` — Displays a formatted list of all active subscriptions for the current user.
*   `/clear` — Instantly flushes all active subscriptions for the user out of the database.

---

## 🚀 Local Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/aome11/crypto-monitoring
   cd crypto-monitoring
   ```

2. **Set up a virtual environment and install dependencies:**
   ```bash
   python -m venv .venv
   # On Windows:
   .venv\Scripts\activate
   # On Linux/macOS:
   source .venv/bin/activate

   pip install -r requirements.txt
   ```

3. **Create a local `.env` configuration file in the root directory:**
   ```text
   BOT_TOKEN=your_telegram_bot_token_from_botfather
   ```

4. **Launch the application:**
   ```bash
   python bot.py
   ```

---

## ⚖️ License
This project is licensed under the open-source **MIT License**. You are free to modify, distribute, or use this code for any personal or commercial use cases.
