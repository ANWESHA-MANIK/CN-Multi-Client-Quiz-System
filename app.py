# =====================================================================
# app.py  —  CN Project: Multi-Client Quiz System (Main Server)
#
# Yeh file do cheezein ek saath handle karti hai:
#   1.  Flask + SocketIO  →  browser clients ke liye (port 5001)
#   2.  TLS TCP Server    →  Python terminal clients ke liye (port 5000)
#
# Flow:
#   - Clients join karte hain  →  "waiting" screen dikhti hai
#   - Admin /server pe jaake "Start Quiz" dabata hai
#   - Quiz shuru hoti hai, har question broadcast hota hai
#   - Timer khatam → next question
#   - Sab questions ke baad final results dikhte hain
# =====================================================================

import ssl
import socket
import json
import threading
from flask import Flask, render_template, request, session, redirect, url_for
from flask_socketio import SocketIO, emit
from collections import defaultdict

# ──────────────────────────────────────────
# Flask + SocketIO initialize karo
# ──────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "cn_quiz_secret_2024"   # Session cookie encrypt karne ke liye

# async_mode='threading' isliye kyunki TLS TCP server bhi threads use karta hai
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ──────────────────────────────────────────
# Network Config
# ──────────────────────────────────────────
HOST      = "0.0.0.0"   # Sab network interfaces pe listen karo (LAN support)
TLS_PORT  = 5000        # Python terminal clients ke liye (TLS encrypted TCP)
WEB_PORT  = 5001        # Browser clients ke liye (HTTP + WebSocket)

# ──────────────────────────────────────────
# Global State  —  poore server ka data yahan
# ──────────────────────────────────────────
questions       = []              # List of {question, answer} dicts
scores          = defaultdict(int)  # Web client scores  →  sid: score
client_states   = {}              # Web client state    →  sid: {name, current_q, answered}
lock            = threading.Lock()  # Thread safety ke liye mutex (web clients)

QUESTION_DURATION = 15            # Har question ke liye seconds

quiz_running          = False     # Abhi quiz chal rahi hai kya?
current_question_index = -1       # Kaunsa question chal raha hai (-1 = koi nahi)
answered_clients      = set()     # Web clients jo is question ka answer de chuke hain

# TCP clients alag dict mein track karo
tcp_clients = {}                  # secure_socket: {name, score, current_q, answered}
tcp_lock    = threading.Lock()    # TCP clients ke liye alag lock


# ──────────────────────────────────────────
# UTILITY FUNCTIONS
# ──────────────────────────────────────────

def get_local_ip():
    """
    Machine ka LAN IP pata karo.
    Google DNS se "route" puchte hain bina actual connection ke.
    Yeh trick consistently sahi IP deti hai even with multiple interfaces.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"   # Fallback: localhost
    finally:
        s.close()
    return ip


def load_questions():
    """
    question.txt se questions load karo.
    Format: Question text|Answer
    Blank lines aur galat format ki lines skip kar do.
    """
    try:
        with open("question.txt", "r") as f:
            for line in f:
                line = line.strip()
                if "|" not in line:
                    continue  # Galat format, skip
                parts = line.split("|", 1)  # Sirf pehle | pe split karo
                if parts[0].strip() and parts[1].strip():
                    questions.append({
                        "question": parts[0].strip(),
                        "answer":   parts[1].strip()
                    })
    except FileNotFoundError:
        print("[ERROR] question.txt nahi mila! Koi questions nahi honge.")


# Server start hote hi questions aur IP load karo
load_questions()
LOCAL_IP = get_local_ip()


# ══════════════════════════════════════════
# FLASK HTTP ROUTES
# ══════════════════════════════════════════

@app.route("/")
def index():
    # Root URL pe aao toh client join page pe redirect karo
    return redirect(url_for("client_join"))


@app.route("/client", methods=["GET", "POST"])
def client_join():
    """
    GET:  Join form dikhao (naam daalo)
    POST: Naam validate karo, session mein save karo, quiz page pe bhejo
    """
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            # Naam khali chhoda toh error dikhao
            return render_template("client.html", error="Naam daalna zaroori hai!", server_ip=LOCAL_IP)
        session["name"] = name
        return redirect(url_for("client_quiz_page"))
    # GET request: sirf form dikhao
    return render_template("client.html", server_ip=LOCAL_IP)


@app.route("/client-quiz")
def client_quiz_page():
    """
    Quiz playing screen.
    Session mein naam nahi hai toh wapas join page pe bhejo.
    """
    if "name" not in session:
        return redirect(url_for("client_join"))
    return render_template("client_quiz.html", name=session["name"])


@app.route("/server")
def server_dashboard():
    """
    Admin control panel.
    Quiz start/reset karna, scores dekhna — sab yahan se.
    """
    return render_template(
        "server.html",
        total_questions=len(questions),
        server_ip=LOCAL_IP,
        web_port=WEB_PORT,
        tls_port=TLS_PORT
    )


# ══════════════════════════════════════════
# WEBSOCKET EVENTS  —  Default Namespace (/)
# Browser clients yahan se connect karte hain
# ══════════════════════════════════════════

@socketio.on("join_quiz")
def handle_join(data):
    """
    Browser client ne join kiya.
    Score aur state register karo.
    Agar quiz pehle se chal rahi hai toh current question bhi bhejo.
    """
    name = (data.get("name", "") or "Player").strip()
    sid  = request.sid   # Har browser connection ka unique socket ID

    with lock:
        scores[sid]       = 0
        client_states[sid] = {
            "name":      name,
            "current_q": -1,     # Abhi koi question assigned nahi
            "answered":  False   # Is question ka answer diya kya?
        }

    # Server admin ko batao — naya player aaya
    socketio.emit("client_joined", {
        "name":          name,
        "score":         0,
        "total_players": len(client_states)
    }, namespace="/server")

    # Agar quiz chal rahi hai toh current question bhejo
    with lock:
        if quiz_running and 0 <= current_question_index < len(questions):
            q = questions[current_question_index]
            client_states[sid]["current_q"] = current_question_index
            emit("all_clients_next", {
                "number":    current_question_index + 1,
                "total":     len(questions),
                "question":  q["question"],
                "time_left": QUESTION_DURATION  # Approximate
            })
        else:
            # Quiz shuru nahi hui — wait state mein rakho
            emit("waiting", {"message": "Host ke quiz start karne ka intezaar karo..."})


@socketio.on("submit_answer")
def handle_answer(data):
    """
    Client ne answer submit kiya.
    - Duplicate answers block karo
    - Correct hai toh score badhao
    - Server dashboard pe update bhejo
    """
    sid = request.sid

    if sid not in client_states:
        return   # Register nahi hai — ignore

    with lock:
        state  = client_states[sid]

        # Pehle se answer de chuka hai? Ignore karo
        if state.get("answered", False):
            return

        user_q = state.get("current_q", -1)

        # Invalid question index? Ignore karo
        if user_q < 0 or user_q >= len(questions):
            return

        # Late joiner agar purana question bheje toh ignore karo
        if user_q != current_question_index:
            return

        # Answer lock karo (dobara submit nahi hoga)
        state["answered"] = True
        answered_clients.add(sid)

        ans     = data.get("answer", "").lower().strip()
        correct = questions[user_q]["answer"].lower().strip()
        is_correct = (ans == correct)

        if is_correct:
            scores[sid] += 1

        response = {
            "name":      state["name"],
            "score":     scores[sid],
            "correct":   is_correct,
            "correct_answer": questions[user_q]["answer"]  # Client ko sahi jawab batao
        }

    # Client ko result confirm karo
    emit("answer_result", response)

    # Server dashboard pe score update karo
    socketio.emit("score_update", {
        "name":  response["name"],
        "score": response["score"]
    }, namespace="/server")


@socketio.on("disconnect")
def handle_disconnect():
    """
    Client disconnect hua (tab band, network cut, etc.)
    Uski entry clean karo aur server ko batao.
    """
    sid = request.sid

    with lock:
        if sid not in client_states:
            return
        name = client_states[sid]["name"]
        del client_states[sid]
        scores.pop(sid, None)
        answered_clients.discard(sid)

    socketio.emit("client_left", {
        "name":          name,
        "total_players": len(client_states)
    }, namespace="/server")


# ══════════════════════════════════════════
# WEBSOCKET EVENTS  —  /server Namespace
# Admin dashboard yahan se connect karta hai
# ══════════════════════════════════════════

@socketio.on("start_quiz", namespace="/server")
def handle_start_quiz():
    """
    Admin ne 'Start Quiz' button dabaya.
    Ek waqt mein sirf ek quiz chal sakti hai.
    """
    global quiz_running

    with lock:
        if quiz_running:
            emit("quiz_error", {"message": "Quiz already chal rahi hai!"})
            return
        if not questions:
            emit("quiz_error", {"message": "question.txt mein koi questions nahi hain!"})
            return
        quiz_running = True

    # Background thread mein quiz chalao — main thread block na ho
    socketio.start_background_task(run_quiz)


@socketio.on("reset_quiz", namespace="/server")
def handle_reset():
    """
    Admin quiz reset karna chahta hai.
    Sab scores aur state clear karo.
    Quiz chal rahi ho tab reset nahi ho sakta.
    """
    global quiz_running, current_question_index, answered_clients

    with lock:
        if quiz_running:
            emit("quiz_error", {"message": "Quiz chal rahi hai! Pehle khatam hone do."})
            return

        # State reset karo
        current_question_index = -1
        answered_clients       = set()
        scores.clear()

        # Har web client ka state bhi reset karo
        for sid in client_states:
            client_states[sid]["current_q"] = -1
            client_states[sid]["answered"]  = False

    # Clients ko reset signal bhejo
    socketio.emit("quiz_reset", {}, namespace="/")
    emit("reset_done", {"message": "Quiz reset ho gayi! Ab dobara start kar sakte ho."})


# ══════════════════════════════════════════
# QUIZ ENGINE  (background thread mein chalta hai)
# ══════════════════════════════════════════

def run_quiz():
    """
    Main quiz loop — har question broadcast karo, timer chalaao, next pe jao.

    Yeh function socketio.start_background_task() ke through chalta hai
    isliye directly thread spawn nahi karte — SocketIO ka apna scheduler hai.
    """
    global current_question_index, answered_clients, quiz_running

    total = len(questions)

    # Quiz shuru ho rahi hai — sab clients ko batao
    socketio.emit("quiz_started", {"total": total}, namespace="/")
    socketio.emit("quiz_started", {"total": total}, namespace="/server")

    for q_index in range(total):

        # ── Question setup ──
        with lock:
            current_question_index = q_index
            answered_clients       = set()
            # Har connected web client ko current question pe set karo
            for sid in client_states:
                client_states[sid]["current_q"] = q_index
                client_states[sid]["answered"]  = False

        q       = questions[q_index]
        payload = {
            "number":    q_index + 1,
            "total":     total,
            "question":  q["question"],
            "time_left": QUESTION_DURATION
        }

        # Question broadcast karo — web clients + server dashboard
        socketio.emit("all_clients_next", payload, namespace="/")
        socketio.emit("all_clients_next", payload, namespace="/server")
        socketio.emit("question_changed", {
            "current_question": q_index + 1,
            "total":            total,
            "question":         q["question"]
        }, namespace="/server")

        # TCP clients ko bhi question bhejo
        _tcp_broadcast_question(q_index, q, total)

        # ── Timer countdown ──
        for remaining in range(QUESTION_DURATION, 0, -1):
            socketio.sleep(1)
            # Dashboard pe live timer update bhejo
            socketio.emit("timer_tick", {
                "remaining":   remaining - 1,
                "question_num": q_index + 1
            }, namespace="/server")

    # ── Quiz khatam! ──

    # Final leaderboard banao
    final_scores = []
    with lock:
        for sid, state in client_states.items():
            final_scores.append({
                "name":  state["name"],
                "score": scores[sid],
                "total": total
            })

    with tcp_lock:
        for sock, state in tcp_clients.items():
            final_scores.append({
                "name":  state["name"],
                "score": state["score"],
                "total": total
            })

    # Score ke hisaab se sort karo (highest first)
    final_scores.sort(key=lambda x: x["score"], reverse=True)

    # Sab clients ko results bhejo
    socketio.emit("quiz_completed", {
        "scores": final_scores,
        "total":  total
    }, namespace="/")
    socketio.emit("quiz_completed", {
        "scores": final_scores,
        "total":  total
    }, namespace="/server")

    # TCP clients ko individual results bhejo
    _tcp_send_results(total)

    # State reset karo — next quiz ke liye ready
    with lock:
        current_question_index = -1
        answered_clients       = set()
        quiz_running           = False


# ══════════════════════════════════════════
# TLS TCP SERVER  —  Terminal clients ke liye
# Port 5000 pe encrypted TCP connections accept karta hai
# ══════════════════════════════════════════

def _tcp_broadcast_question(q_index, question, total):
    """
    Sab connected TCP clients ko current question bhejo.
    JSON + newline delimiter protocol use karo.
    Dead connections ko clean karo.
    """
    payload = json.dumps({
        "type":     "question",
        "number":   q_index + 1,
        "total":    total,
        "question": question["question"]
    }) + "\n"

    dead = []
    with tcp_lock:
        for sock, state in tcp_clients.items():
            try:
                state["current_q"] = q_index
                state["answered"]  = False
                sock.sendall(payload.encode())
            except Exception:
                dead.append(sock)   # Connection toot gayi

    for sock in dead:
        _tcp_remove_client(sock)


def _tcp_send_results(total):
    """
    Quiz end pe har TCP client ko unka apna score bhejo.
    """
    dead = []
    with tcp_lock:
        for sock, state in tcp_clients.items():
            try:
                result = json.dumps({
                    "type":  "end",
                    "score": state["score"],
                    "total": total
                }) + "\n"
                sock.sendall(result.encode())
            except Exception:
                dead.append(sock)

    for sock in dead:
        _tcp_remove_client(sock)


def _tcp_remove_client(sock):
    """
    TCP client ko safely remove karo aur socket band karo.
    Server dashboard ko disconnect notify karo.
    """
    with tcp_lock:
        state = tcp_clients.pop(sock, None)
    try:
        sock.close()
    except Exception:
        pass
    if state:
        print(f"[TCP] Disconnected: {state['name']}")
        socketio.emit("client_left", {
            "name":          state["name"],
            "total_players": len(client_states)
        }, namespace="/server")


def _handle_tcp_client(secure_conn, addr):
    """
    Ek TCP client ka poora lifecycle handle karo.
    Har client ke liye yeh function alag thread mein chalta hai.

    Protocol:
        S → "NAME"
        C → username (plain text)
        S → "READY"
        --- quiz loop ---
        S → {"type":"question", "number":N, "total":T, "question":"..."}\n
        C → {"answer":"..."}\n
        --- quiz end ---
        S → {"type":"end", "score":N, "total":T}\n
    """
    print(f"[TCP] New connection: {addr}")
    name = f"Client_{addr[1]}"   # Default naam jab tak user na de

    try:
        # ── Handshake: naam maango ──
        secure_conn.sendall(b"NAME")
        raw_name = secure_conn.recv(1024).decode().strip()
        if raw_name:
            name = raw_name

        # ── Handshake: confirm karo ──
        secure_conn.sendall(b"READY")
        print(f"[TCP] Player joined: {name} from {addr}")

        # TCP client register karo
        with tcp_lock:
            tcp_clients[secure_conn] = {
                "name":      name,
                "score":     0,
                "current_q": -1,
                "answered":  False
            }

        # Server dashboard ko notify karo
        socketio.emit("client_joined", {
            "name":          name,
            "score":         0,
            "total_players": len(client_states) + len(tcp_clients)
        }, namespace="/server")

        # ── Main receive loop ──
        # TCP stream hai, messages split ho ke aa sakte hain
        # isliye buffer banao aur newline pe split karo
        buffer = ""

        while True:
            data = secure_conn.recv(4096).decode()
            if not data:
                break   # Connection close ho gayi

            buffer += data

            # Complete messages process karo
            while "\n" in buffer:
                msg, buffer = buffer.split("\n", 1)
                msg = msg.strip()
                if not msg:
                    continue

                try:
                    payload = json.loads(msg)
                    ans     = payload.get("answer", "").lower().strip()

                    with tcp_lock:
                        state = tcp_clients.get(secure_conn)
                        if not state:
                            continue

                        # Duplicate answer block karo
                        if state.get("answered", False):
                            continue

                        q_idx = state["current_q"]
                        if q_idx < 0 or q_idx >= len(questions):
                            continue

                        state["answered"] = True
                        correct = questions[q_idx]["answer"].lower().strip()
                        if ans == correct:
                            state["score"] += 1

                    # Server dashboard pe score update karo
                    with tcp_lock:
                        current_score = tcp_clients.get(secure_conn, {}).get("score", 0)

                    socketio.emit("score_update", {
                        "name":  name,
                        "score": current_score
                    }, namespace="/server")

                except json.JSONDecodeError:
                    # Partial/invalid JSON — buffer mein aur data aayega
                    continue

    except Exception as e:
        print(f"[TCP] Error with {addr}: {e}")
    finally:
        _tcp_remove_client(secure_conn)


def run_tcp_server():
    """
    TLS TCP server — background mein forever chalta hai.
    Har naye client ke liye daemon thread spawn karta hai.

    TLS context: self-signed cert use kar rahe hain (CN project ke liye theek hai).
    Production mein proper CA-signed certificate hona chahiye.
    """
    try:
        # TLS context banao — server side
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain("cert.pem", "key.pem")

        # Raw TCP socket
        raw_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # SO_REUSEADDR: server restart ke baad port immediately free ho jaye
        raw_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        raw_server.bind((HOST, TLS_PORT))
        raw_server.listen(20)   # Max 20 pending connections queue mein

        print(f"[TCP] TLS Server ready on port {TLS_PORT}")

        while True:
            try:
                conn, addr = raw_server.accept()   # Blocking — naye connection ka wait
                try:
                    # TLS handshake karo
                    secure_conn = context.wrap_socket(conn, server_side=True)
                except ssl.SSLError as e:
                    print(f"[TCP] TLS handshake failed {addr}: {e}")
                    conn.close()
                    continue

                # Har client ke liye alag thread — ek client dusre ko block na kare
                t = threading.Thread(
                    target=_handle_tcp_client,
                    args=(secure_conn, addr),
                    daemon=True   # Main program band → ye thread bhi band
                )
                t.start()

            except Exception as e:
                print(f"[TCP] Accept error: {e}")

    except Exception as e:
        print(f"[TCP] Server failed to start: {e}")


# ══════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "═" * 56)
    print("   CN PROJECT  ▸  MULTI CLIENT QUIZ SYSTEM")
    print("═" * 56)
    print(f"   Admin Dashboard  →  http://{LOCAL_IP}:{WEB_PORT}/server")
    print(f"   Player Join      →  http://{LOCAL_IP}:{WEB_PORT}/client")
    print(f"   TLS TCP Port     →  {TLS_PORT}   (python client.py {LOCAL_IP})")
    print(f"   Questions loaded →  {len(questions)}")
    print("═" * 56 + "\n")

    # TLS TCP server background thread mein chalao
    tcp_thread = threading.Thread(target=run_tcp_server, daemon=True)
    tcp_thread.start()

    # Flask + SocketIO main thread mein chalao
    # use_reloader=False — warna do TCP server threads start ho jayenge
    socketio.run(app, host="0.0.0.0", port=WEB_PORT, debug=False, use_reloader=False)
