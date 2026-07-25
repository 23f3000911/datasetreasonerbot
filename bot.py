import json, time, os, threading
from flask import Flask, send_file
from openai import OpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
AIPIPE_TOKEN = os.environ["AIPIPE_TOKEN"]
LOG_URL = os.environ["LOG_URL"]

client = OpenAI(base_url="https://aipipe.org/openai/v1", api_key=AIPIPE_TOKEN)
LOG_FILE = "run.jsonl"
MAX_HISTORY = 20

flask_app = Flask(__name__)

@flask_app.get("/")
def home():
    return "Bot is running", 200

@flask_app.get("/run.jsonl")
def serve_log():
    if not os.path.exists(LOG_FILE):
        open(LOG_FILE, "a").close()
    return send_file(LOG_FILE, mimetype="application/json")

conversation_history = {}

def log_event(event: dict):
    event["timestamp"] = time.time()
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(event) + "\n")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    log_event({"type": "incoming", "chat_id": chat_id, "text": user_text})

    history = conversation_history.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_text})

    system_prompt = """
        You are a careful data-analysis assistant.
        Always answer ONLY the user's most recent message.
        Previous messages are context only. Use them only if they contain information
        required to answer the final message.
        The user's final message specifies the exact JSON structure that must be returned.
        Your reply MUST:
        - be exactly one valid JSON object
        - contain exactly the keys requested by the user's message
        - not include markdown
        - not include explanations
        - not include code fences
        - not include extra text
        If the message references a public dataset or URL, use it.
        If the data is included inline, compute the answer from that data.
        Return only the JSON object.
        """

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role": "system", "content": system_prompt}] + history[-MAX_HISTORY:],
    )
    reply_text = response.choices[0].message.content.strip()
    history.append({"role": "assistant", "content": reply_text})

    try:
        parsed = json.loads(reply_text)
    except json.JSONDecodeError:
        start = reply_text.find("{")
        end = reply_text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(reply_text[start:end + 1])
            except Exception:
                parsed = {"answer": reply_text.strip()}
        else:
            parsed = {"answer": reply_text.strip()}

    parsed["log_url"] = LOG_URL
    final_reply = json.dumps(parsed, separators=(",", ":"))

    log_event({"type": "outgoing", "chat_id": chat_id, "text": final_reply})
    await update.message.reply_text(final_reply)

def start_log_server():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

threading.Thread(target=start_log_server, daemon=True).start()

print("Bot is running on Railway...")
app.run_polling()