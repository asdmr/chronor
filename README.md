# Personal Time & Activity Tracker Telegram Bot

[![Python Version](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A friendly Telegram bot designed to help you meticulously track your time and activities throughout the day, gain insights through daily reports, and improve your productivity.

## Features ✨

* **Periodic Activity Polling:** The bot proactively asks "What are you doing right now?" at regular intervals (default: every 30 mins during configurable hours).
* **Simple Activity Logging:** Just reply to the bot's question to log your current activity.
* **Activity Editing:** Made a mistake? Edit the description of past activities using an interactive menu via the `/report` command.
* **Timezone Support:** Set your local timezone (`/set_timezone`) to ensure polling and reports align with your day.
* **Configurable Schedule:**
    * Set your preferred "active hours" for polling (`/set_poll_window`).
    * Set the hour you want to receive your daily report (`/set_report_time`).
* **Daily Reports:** Get daily summaries of your logged activities sent as a `.txt` file:
    * Merged chronological activity list (`/report`).
    * Automatic delivery of the previous day's report around your preferred time.
* **Interactive Controls:** Uses inline buttons for date selection and editing, and reply keyboard buttons for quick command access.
* **Owner-Only Commands:** Includes `/asknow` for manually triggering the activity poll (requires `OWNER_ID` setup).

## Technology Stack 🛠️

* **Language:** Python 3.12
* **Core Library:** [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) (v22+)
* **Scheduling:** APScheduler (via PTB's JobQueue)
* **Configuration:** python-dotenv
* **Timezones:** zoneinfo (Python Standard Library)
* **Database:** SQLite

## Setup & Installation ⚙️

1.  **Prerequisites:**
    * Python 3.12 or higher installed.
    * Git installed.

2.  **Clone the Repository:**
    ```bash
    git clone https://github.com/asdmr/chronor.git
    cd chronor
    ```

3.  **Create Virtual Environment:**
    ```bash
    python -m venv .venv
    # Activate it:
    # Windows (CMD/PowerShell):
    .\.venv\Scripts\activate
    # Linux/macOS/Git Bash:
    source .venv/bin/activate
    ```

4.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

5.  **Configure Environment Variables:**
    * Create a file named `.env` in the root directory of the project.
    * Add the following lines, replacing the placeholder values:
        ```dotenv
        BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
        OWNER_ID="YOUR_TELEGRAM_USER_ID"
        ```
        * Get `BOT_TOKEN` from [@BotFather](https://t.me/BotFather) on Telegram.
        * Get your `OWNER_ID` by messaging [@userinfobot](https://t.me/userinfobot) on Telegram (or similar). `OWNER_ID` is required for the `/asknow` command and timezone-based scheduling logic on startup.

6.  **Initialize Database:**
    * The first time you run the bot, it will automatically create the `data/` folder and the `activities.db` SQLite database file with the necessary tables.

7.  **Run the Bot:**
    ```bash
    python bot.py
    ```

## Configuration 🔧

The bot uses a `.env` file in the project root for configuration:

* `BOT_TOKEN`: **Required.** Your unique token obtained from @BotFather.
* `OWNER_ID`: **Required.** Your numeric Telegram User ID. Needed for owner-specific commands and initial timezone lookup for scheduling.

Make sure the `.env` file is present and contains valid values before running the bot. The `.gitignore` file prevents this file from being committed to Git.

## Usage 📖

1.  **Start:** Open a chat with your bot on Telegram and send the `/start` command.
2.  **Set Timezone:** Use the `/set_timezone <IANA_Name>` command (e.g., `/set_timezone Asia/Almaty`) to set your local timezone. This is important for correct timing of polls and reports. Use the "🌐 Set Timezone" button for instructions.
3.  **(Optional) Configure Schedule:**
    * Use `/set_poll_window <start_hour> <end_hour>` (e.g., `/set_poll_window 9 21`) to define when the bot should ask about your activity (default is 8-22).
    * Use `/set_report_time <hour>` (e.g., `/set_report_time 7`) to set the hour (0-23) when you'd like to receive the daily report (default is 8).
4.  **Log Activities:** When the bot asks "🤔 What are you doing right now?", simply reply with a description of your activity.
5.  **Get Reports:**
    * Use the "📊 Activity Report" button or type `/report`. Select "Today" or "Yesterday" using the inline buttons, or type `/report YYYY-MM-DD` for a specific date.
    * The bot will show an interactive list with "✏️ Edit" buttons and a "⬇️ Download .txt" button.
6.  **Edit Activities:** Click the "✏️ Edit" button next to an activity in the report view, then send the new description as a message.
7.  **Other Commands:** Use `/help` or the reply keyboard buttons for other available actions.

## License 📄

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
