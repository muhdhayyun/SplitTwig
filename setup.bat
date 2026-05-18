@echo off
pip install -r requirements.txt
if not exist .env (
    copy .env.example .env
    echo.
    echo Created .env — open it and paste your BOT_TOKEN
)
echo.
echo Setup done. Run: python bot.py
pause
