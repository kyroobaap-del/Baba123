from flask import Flask, request, jsonify
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import binascii
import aiohttp
import requests
import json
import like_pb2
import uid_generator_pb2
import visit_count_pb2
from google.protobuf.message import DecodeError
from collections import OrderedDict
import time
import datetime
import pytz
import sqlite3

IST = pytz.timezone("Asia/Kolkata")


app = Flask(__name__)

# ✅ Valid API keys
VALID_API_KEYS = {
    "POPU"  # don't change warna api nhi chalega
}

# 🔢 Like limit tracking
daily_limit = 210
used_count = 0



def init_db():
    conn = sqlite3.connect("keys.db")
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS temp_keys (
        key TEXT PRIMARY KEY,
        limit_per_day INTEGER,
        used_today INTEGER,
        expiry INTEGER,
        last_reset INTEGER
    )''')

    conn.commit()
    conn.close()

init_db()

def reset_daily_if_needed(key_data):
    now = datetime.datetime.now(IST)

    last_reset = datetime.datetime.fromtimestamp(
        key_data["last_reset"], IST
    )

    today_4am = now.replace(hour=4, minute=0, second=0, microsecond=0)

    if now < today_4am:
        today_4am -= datetime.timedelta(days=1)

    if last_reset < today_4am:
        key_data["used_today"] = 0
        key_data["last_reset"] = int(time.time())

def load_tokens(region):
    try:
        if region == "IND":
            with open("token_ind.json", "r") as f:
                tokens = json.load(f)
        elif region in {"BR", "US", "SAC", "NA"}:
            with open("token_br.json", "r") as f:
                tokens = json.load(f)
        else:
            with open("token_bd.json", "r") as f:
                tokens = json.load(f)
        return tokens
    except Exception as e:
        app.logger.error(f"Error loading tokens for region {region}: {e}")
        return None


def encrypt_message(plaintext):
    try:
        key = b'Yg&tc%DEuh6%Zc^8'
        iv = b'6oyZDr22E3ychjM%'
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded_message = pad(plaintext, AES.block_size)
        encrypted_message = cipher.encrypt(padded_message)
        return binascii.hexlify(encrypted_message).decode('utf-8')
    except Exception as e:
        app.logger.error(f"Error encrypting message: {e}")
        return None


def create_protobuf_message(user_id, region):
    try:
        message = like_pb2.like()
        message.uid = int(user_id)
        message.region = region
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating protobuf message: {e}")
        return None


async def send_request(encrypted_uid, token, url):
    try:
        edata = bytes.fromhex(encrypted_uid)
        headers = {
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Expect": "100-continue",
            "X-Unity-Version": "2018.4.11f1",
            "X-GA": "v1 1",
            "ReleaseVersion": "OB54"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=edata, headers=headers) as response:
                return await response.text()
    except Exception as e:
        app.logger.error(f"Exception in send_request: {e}")
        return None


async def send_multiple_requests(uid, region, url):
    try:
        protobuf_message = create_protobuf_message(uid, region)
        if protobuf_message is None:
            return None
        encrypted_uid = encrypt_message(protobuf_message)
        if encrypted_uid is None:
            return None
        tokens = load_tokens(region)
        if tokens is None:
            return None
        tasks = []
        for i in range(100):
            token = tokens[i % len(tokens)]["token"]
            tasks.append(send_request(encrypted_uid, token, url))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results
    except Exception as e:
        app.logger.error(f"Exception in send_multiple_requests: {e}")
        return None


def create_protobuf(uid):
    try:
        message = uid_generator_pb2.uid_generator()
        message.saturn_ = int(uid)
        message.garena = 1
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating uid protobuf: {e}")
        return None


def enc(uid):
    protobuf_data = create_protobuf(uid)
    if protobuf_data is None:
        return None
    return encrypt_message(protobuf_data)


def make_request(encrypt, region, token):
    try:
        if region == "IND":
            url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
        elif region in {"BR", "US", "SAC", "NA"}:
            url = "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
        else:
            url = "https://clientbp.ggblueshark.com/GetPlayerPersonalShow"
        edata = bytes.fromhex(encrypt)
        headers = {
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Expect": "100-continue",
            "X-Unity-Version": "2018.4.11f1",
            "X-GA": "v1 1",
            "ReleaseVersion": "OB54"
        }
        response = requests.post(url, data=edata, headers=headers, verify=False)
        binary = response.content
        decoded = visit_count_pb2.Info()
        decoded.ParseFromString(binary)
        return decoded
    except DecodeError as e:
        app.logger.error(f"DecodeError: {e}")
        return None
    except Exception as e:
        app.logger.error(f"Error in make_request: {e}")
        return None


@app.route('/like', methods=['GET'])
def handle_requests():
    global used_count

    api_key = request.args.get("key")
    current_time = int(time.time())

    # 🔗 DB connect
    conn = sqlite3.connect("keys.db")
    c = conn.cursor()

    # 🔍 key fetch
    c.execute("SELECT * FROM temp_keys WHERE key=?", (api_key,))
    row = c.fetchone()

    # ✅ Normal key
    if api_key in VALID_API_KEYS:
        key_data = None

    # ✅ Temp key
    elif row:
        key_data = {
            "key": row[0],
            "limit_per_day": row[1],
            "used_today": row[2],
            "expiry": row[3],
            "last_reset": row[4]
        }

        # ❌ Expired
        if current_time > key_data["expiry"]:
            conn.close()
            return {"error": "Key expired"}, 403

        # 🔁 Reset check
        reset_daily_if_needed(key_data)

        # 🔁 Save reset to DB
        c.execute("""
            UPDATE temp_keys 
            SET used_today=?, last_reset=? 
            WHERE key=?
        """, (key_data["used_today"], key_data["last_reset"], api_key))
        conn.commit()

        # ❌ Limit check
        if key_data["used_today"] >= key_data["limit_per_day"]:
            conn.close()
            return {"error": "Daily limit reached"}, 403

    # ❌ Invalid
    else:
        conn.close()
        result = OrderedDict([
            ("error", "Invalid or missing API key"),
            ("status", 3)
        ])
        return app.response_class(
            response=json.dumps(result, separators=(',', ':')),
            status=401,
            mimetype='application/json'
        )

    uid = request.args.get("uid")
    region = request.args.get("region", "").upper()

    if not uid or not region:
        conn.close()
        return {"error": "UID and region are required"}, 400

    try:
        tokens = load_tokens(region)
        if not tokens:
            raise Exception("Failed to load tokens.")

        token = tokens[0]['token']
        encrypted_uid = enc(uid)

        if encrypted_uid is None:
            raise Exception("Encryption of UID failed.")

        before = make_request(encrypted_uid, region, token)
        if before is None:
            raise Exception("Failed to get initial info.")

        before_like = before.AccountInfo.Likes

        # 🔥 URL select
        if region == "IND":
            url = "https://client.ind.freefiremobile.com/LikeProfile"
        elif region in {"BR", "US", "SAC", "NA"}:
            url = "https://client.us.freefiremobile.com/LikeProfile"
        else:
            url = "https://clientbp.ggblueshark.com/LikeProfile"

        asyncio.run(send_multiple_requests(uid, region, url))

        after = make_request(encrypted_uid, region, token)
        if after is None:
            raise Exception("Failed to get final info.")

        after_like = after.AccountInfo.Likes
        like_given = after_like - before_like
        status = 1 if like_given > 0 else 2

        # ✅ Global count
        if status == 1:
            used_count += 1

        # ✅ Temp key usage update
        if row and status == 1:
            c.execute("""
                UPDATE temp_keys 
                SET used_today = used_today + 1 
                WHERE key=?
            """, (api_key,))
            conn.commit()

        remaining = max(daily_limit - used_count, 0)

        result = OrderedDict([
            ("LikesGivenByAPI", like_given),
            ("LikesafterCommand", after_like),
            ("LikesbeforeCommand", before_like),
            ("PlayerNickname", after.AccountInfo.PlayerNickname),
            ("Level", after.AccountInfo.Levels),
            ("Region", after.AccountInfo.PlayerRegion),
            ("UID", after.AccountInfo.UID),
            ("status", status),
            ("daily_limit", daily_limit),
            ("used", used_count),
            ("remaining", remaining)
        ])

        conn.close()

        return app.response_class(
            response=json.dumps(result, separators=(',', ':')),
            status=200,
            mimetype='application/json'
        )

    except Exception as e:
        conn.close()
        app.logger.error(f"Error: {e}")
        return {"error": str(e)}, 500


@app.route('/temp_key', methods=['GET'])
def create_temp_key():
    key = request.args.get("key")
    remain = int(request.args.get("remain", 1))
    days = int(request.args.get("days", 1))

    if not key:
        return {"error": "Key required"}, 400

    expiry = int(time.time()) + (days * 86400)

    conn = sqlite3.connect("keys.db")
    c = conn.cursor()

    c.execute("REPLACE INTO temp_keys VALUES (?, ?, ?, ?, ?)",
              (key, remain, 0, expiry, int(time.time())))

    conn.commit()
    conn.close()

    return {
        "status": "created",
        "key": key,
        "daily_limit": remain,
        "valid_days": days
    }

@app.route('/temp_remain', methods=['GET'])
def temp_remain():
    key = request.args.get("key")

    conn = sqlite3.connect("keys.db")
    c = conn.cursor()

    c.execute("SELECT * FROM temp_keys WHERE key=?", (key,))
    row = c.fetchone()

    if not row:
        conn.close()
        return {"error": "Invalid key"}, 404

    data = {
        "key": row[0],
        "limit_per_day": row[1],
        "used_today": row[2],
        "expiry": row[3],
        "last_reset": row[4]
    }

    # 🔁 Reset check
    reset_daily_if_needed(data)

    # 🔁 Save reset
    c.execute("""
        UPDATE temp_keys 
        SET used_today=?, last_reset=? 
        WHERE key=?
    """, (data["used_today"], data["last_reset"], key))

    conn.commit()

    now = int(time.time())

    result = {
        "key": key,
        "daily_limit": data["limit_per_day"],
        "used_today": data["used_today"],
        "remaining_today": data["limit_per_day"] - data["used_today"],
        "expires_in_sec": max(data["expiry"] - now, 0),
        "reset_time": "4:00 AM IST"
    }

    conn.close()
    return result

# 🆕 /remain endpoint
@app.route('/remain', methods=['GET'])
def remain_info():
    global used_count  # ✅ fix added

    remaining = max(daily_limit - used_count, 0)
    data = {
        "daily_limit": daily_limit,
        "remaining": remaining,
        "used": used_count,
        "reset_info": "4:00 AM IST"
    }
    return jsonify(data)


if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
