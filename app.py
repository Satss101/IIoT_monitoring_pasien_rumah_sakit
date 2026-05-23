"""
BNSP IoT Monitoring System
--------------------------
Features:
- Modbus TCP reading (FC4 - Read Input Registers)
- MySQL database storage
- Telegram bot integration
- Flask web dashboard with login
"""

import threading
import time
import logging
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, redirect, url_for, session, request, jsonify
from pymodbus.client import ModbusTcpClient
import pymysql
import telebot
from telebot import types

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
MODBUS_HOST     = "192.168.18.254"
MODBUS_PORT     = 502
MODBUS_UNIT_ID  = 1
MODBUS_ADDRESS  = 1        # starting address (0-based = 1 means register 2 in PLC)
MODBUS_QUANTITY = 5

DB_HOST     = "127.0.0.1"
DB_PORT     = 3306
DB_USER     = "root"
DB_PASSWORD = ""           # ← ganti sesuai password MySQL Anda
DB_NAME     = "db_bnsp"

TELEGRAM_TOKEN   = "8262297802:AAGRggGZZQ3otthS2oR264IjWzcLKHguRjM"
TELEGRAM_CHAT_ID = "1284922119"

WEB_USER     = "admin"
WEB_PASSWORD = "admin"
SECRET_KEY   = "bnsp-secret-2024"

READ_INTERVAL = 3   # detik

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bnsp_iot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# FLASK APP
# ─────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = SECRET_KEY

# ─────────────────────────────────────────────
# DATABASE HELPERS
# ─────────────────────────────────────────────
def get_db_no_schema():
    """Koneksi MySQL tanpa memilih database (untuk CREATE DATABASE)."""
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )


def get_db():
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )


def init_db():
    """Buat database dan tabel jika belum ada."""
    # Langkah 1: buat database jika belum ada (koneksi tanpa database)
    try:
        conn = get_db_no_schema()
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.close()
        log.info(f"Database '{DB_NAME}' siap.")
    except Exception as e:
        log.error(f"Gagal membuat database: {e}")
        raise

    # Langkah 2: buat tabel
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS monitoring (
                id        INT AUTO_INCREMENT PRIMARY KEY,
                temp      FLOAT,
                hum       FLOAT,
                spo2      FLOAT,
                hr        FLOAT,
                gsr       FLOAT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS setting (
                id        INT AUTO_INCREMENT PRIMARY KEY,
                threshold FLOAT DEFAULT 95.0
            )
        """)
        # Seed default threshold jika belum ada
        cur.execute("SELECT COUNT(*) AS cnt FROM setting")
        if cur.fetchone()["cnt"] == 0:
            cur.execute("INSERT INTO setting (threshold) VALUES (95.0)")
    conn.close()
    log.info("Tabel database berhasil diinisialisasi.")


def save_reading(temp, hum, spo2, hr, gsr):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO monitoring (temp, hum, spo2, hr, gsr) VALUES (%s,%s,%s,%s,%s)",
            (temp, hum, spo2, hr, gsr)
        )
    conn.close()


def get_latest():
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM monitoring ORDER BY timestamp DESC LIMIT 1")
        row = cur.fetchone()
    conn.close()
    return row


def get_history(limit=50):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM monitoring ORDER BY timestamp DESC LIMIT %s", (limit,)
        )
        rows = cur.fetchall()
    conn.close()
    return rows


def get_threshold():
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("SELECT threshold FROM setting ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
    conn.close()
    return row["threshold"] if row else 95.0


def set_threshold(value):
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("UPDATE setting SET threshold=%s", (value,))
        if cur.rowcount == 0:
            cur.execute("INSERT INTO setting (threshold) VALUES (%s)", (value,))
    conn.close()

# ─────────────────────────────────────────────
# MODBUS READER
# ─────────────────────────────────────────────
latest_data = {
    "temp": 0, "hum": 0, "spo2": 0, "hr": 0, "gsr": 0,
    "timestamp": None, "status": "Connecting..."
}
alert_sent = False   # cegah spam alert


def scale(raw, factor=10.0):
    """Konversi raw register ke nilai float (sesuaikan factor dengan perangkat Anda)."""
    return round(raw / factor, 1)


def read_registers(client):
    """Coba semua cara pemanggilan modbus yang ada di berbagai versi pymodbus."""
    # pymodbus >= 3.x
    try:
        return client.read_input_registers(
            address=MODBUS_ADDRESS, count=MODBUS_QUANTITY, slave=MODBUS_UNIT_ID
        )
    except TypeError:
        pass
    # pymodbus 2.x
    try:
        return client.read_input_registers(
            address=MODBUS_ADDRESS, count=MODBUS_QUANTITY, unit=MODBUS_UNIT_ID
        )
    except TypeError:
        pass
    # fallback tanpa unit_id
    return client.read_input_registers(
        address=MODBUS_ADDRESS, count=MODBUS_QUANTITY
    )


def modbus_reader():
    global latest_data, alert_sent
    client = ModbusTcpClient(MODBUS_HOST, port=MODBUS_PORT)
    log.info(f"Modbus target: {MODBUS_HOST}:{MODBUS_PORT} unit={MODBUS_UNIT_ID}")

    while True:
        try:
            if not client.is_socket_open():
                connected = client.connect()
                if not connected:
                    log.warning("Gagal koneksi Modbus, retry 3s...")
                    latest_data["status"] = "Connecting..."
                    time.sleep(3)
                    continue

            result = read_registers(client)

            if result.isError():
                log.warning(f"Modbus error: {result}")
                latest_data["status"] = "Modbus Error"
            else:
                regs = result.registers
                spo2 = scale(regs[0])
                hr  = scale(regs[1])
                temp = scale(regs[2])
                hum   = scale(regs[3])
                gsr  = regs[4] / 10          # GSR biasanya tidak dibagi

                now = datetime.now()
                latest_data = {
                    "temp": temp, "hum": hum, "spo2": spo2,
                    "hr": hr, "gsr": gsr,
                    "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "status": "Online"
                }

                save_reading(temp, hum, spo2, hr, gsr)
                log.info(f"Read: T={temp} H={hum} SpO2={spo2} HR={hr} GSR={gsr}")

                # ── Cek threshold SpO2 ──
                threshold = get_threshold()
                if spo2 < threshold and not alert_sent:
                    msg = (
                        f"⚠️ *PERINGATAN SpO2 RENDAH!*\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"🩸 SpO2     : *{spo2}%*\n"
                        f"📊 Batas    : *{threshold}%*\n"
                    )
                    send_telegram(msg)
                    alert_sent = True
                elif spo2 >= threshold:
                    alert_sent = False

        except Exception as e:
            log.error(f"Modbus exception: {e}")
            latest_data["status"] = f"Error: {e}"
            try:
                client.close()
            except:
                pass
            client = ModbusTcpClient(MODBUS_HOST, port=MODBUS_PORT)

        time.sleep(READ_INTERVAL)

# ─────────────────────────────────────────────
# TELEGRAM BOT
# ─────────────────────────────────────────────
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="Markdown")


def send_telegram(message):
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
    except Exception as e:
        log.error(f"Telegram send error: {e}")


@bot.message_handler(commands=["start"])
def cmd_start(message):
    text = (
        "👋 *Selamat datang di BNSP IoT Monitor!*\n\n"
        "🤖 Berikut perintah yang tersedia:\n\n"
        "📋 `/ceksituasi`\n"
        "   └ Menampilkan data sensor terkini\n"
        "      (Suhu, Kelembapan, SpO2, Detak Jantung, GSR)\n\n"
        "⚙️ `/setbatas <nilai>`\n"
        "   └ Mengatur ambang batas SpO2\n"
        "      Contoh: `/setbatas 98`\n"
        "      _(Bot akan mengirim peringatan jika SpO2 melebihi nilai ini)_\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *BNSP Health Monitoring System*"
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["ceksituasi"])
def cmd_ceksituasi(message):
    row = get_latest()
    threshold = get_threshold()
    if not row:
        bot.reply_to(message, "⚠️ Belum ada data yang tersimpan.")
        return

    status_spo2 = "🔴 RENDAH" if row["spo2"] < threshold else "🟢 Normal"
    text = (
        f"📊 *Situasi Sensor Terkini*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🌡️ Suhu          : *{row['temp']}°C*\n"
        f"💧 Kelembapan    : *{row['hum']}%*\n"
        f"🩸 SpO2          : *{row['spo2']}%* {status_spo2}\n"
        f"❤️ Detak Jantung : *{row['hr']} bpm*\n"
        f"💦 GSR (Keringat): *{row['gsr']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 Batas SpO2    : {threshold}%\n"
        f"🕐 Waktu         : {row['timestamp']}"
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["setbatas"])
def cmd_setbatas(message):
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ Format: `/setbatas <nilai>`\nContoh: `/setbatas 98`")
        return
    try:
        val = float(parts[1])
        if not (0 <= val <= 100):
            raise ValueError
        set_threshold(val)
        bot.reply_to(
            message,
            f"✅ *Ambang batas SpO2 berhasil diubah!*\n"
            f"📌 Batas baru: *{val}%*\n"
            f"Bot akan mengirim peringatan jika SpO2 < {val}%"
        )
        log.info(f"Threshold updated to {val} via Telegram")
    except ValueError:
        bot.reply_to(message, "❌ Nilai tidak valid. Masukkan angka 0–100.")


def telegram_kill_old_sessions():
    """
    Paksa matikan sesi getUpdates lama dengan mengirim timeout=0.
    Ini adalah satu-satunya cara yang bisa memutus 409 conflict.
    """
    import urllib.request, urllib.error, json as _json
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    payload = _json.dumps({"timeout": 0, "offset": -1}).encode()
    req = urllib.request.Request(url, data=payload,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            log.info("Force-kill sesi Telegram lama: OK")
    except Exception as e:
        log.warning(f"Force-kill sesi: {e}")


def telegram_polling():
    """Manual polling loop tanpa threading internal telebot."""
    log.info("Telegram bot polling started.")

    # Step 1: hapus webhook
    try:
        bot.remove_webhook()
        log.info("Webhook Telegram dihapus.")
    except Exception as e:
        log.warning(f"remove_webhook: {e}")
    time.sleep(2)

    # Step 2: paksa matikan sesi getUpdates lama
    telegram_kill_old_sessions()
    time.sleep(3)

    # Step 3: mulai polling manual
    offset = None
    log.info("Manual polling Telegram dimulai.")

    while True:
        try:
            updates = bot.get_updates(offset=offset, timeout=25)
            for upd in updates:
                offset = upd.update_id + 1
                try:
                    bot.process_new_updates([upd])
                except Exception as pe:
                    log.error(f"Process update error: {pe}")
        except Exception as e:
            err = str(e)
            if "409" in err:
                log.warning("Telegram 409 conflict, paksa kill & tunggu 20 detik...")
                telegram_kill_old_sessions()
                time.sleep(20)
            elif "504" in err or "502" in err or "ReadTimeout" in err:
                log.warning("Telegram timeout, retry 3s...")
                time.sleep(3)
            else:
                log.error(f"Telegram polling error: {e}")
                time.sleep(5)

# ─────────────────────────────────────────────
# FLASK ROUTES
# ─────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/", methods=["GET"])
@login_required
def index():
    return render_template("dashboard.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == WEB_USER and password == WEB_PASSWORD:
            session["logged_in"] = True
            session["username"] = username
            return redirect(url_for("index"))
        else:
            error = "Username atau password salah!"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/latest")
@login_required
def api_latest():
    return jsonify(latest_data)


@app.route("/api/history")
@login_required
def api_history():
    rows = get_history(100)
    # Convert datetime objects to string
    for r in rows:
        if r.get("timestamp"):
            r["timestamp"] = str(r["timestamp"])
    return jsonify(rows)


@app.route("/api/threshold", methods=["GET"])
@login_required
def api_get_threshold():
    return jsonify({"threshold": get_threshold()})


@app.route("/api/threshold", methods=["POST"])
@login_required
def api_set_threshold():
    data = request.get_json()
    try:
        val = float(data.get("threshold", 95))
        if not (0 <= val <= 100):
            raise ValueError
        set_threshold(val)
        log.info(f"Threshold set to {val} via Web")
        return jsonify({"success": True, "threshold": val})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    # Init DB
    init_db()

    # Start Modbus reader thread
    t_modbus = threading.Thread(target=modbus_reader, daemon=True)
    t_modbus.start()
    log.info("Modbus reader thread started.")

    # Start Telegram bot thread
    t_telegram = threading.Thread(target=telegram_polling, daemon=True)
    t_telegram.start()
    log.info("Telegram bot thread started.")

    # Start Flask
    log.info("Starting Flask server on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)