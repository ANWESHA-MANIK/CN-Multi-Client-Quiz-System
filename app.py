import ssl
import socket
import threading
from flask import Flask, render_template, request, session, redirect, url_for
from flask_socketio import SocketIO, emit
from collections import defaultdict

app = Flask(__name__)
app.secret_key = "quiz_secret_key"

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

HOST = "0.0.0.0"
TLS_PORT = 5000
WEB_PORT = 5001

questions = []
scores = defaultdict(int)
client_states = {}
lock = threading.Lock()

QUESTION_DURATION = 10
quiz_running = False
quiz_completed_flag = False

# ✅ NEW GLOBALS
current_question_index = -1
answered_clients = set()

# 🔐 GET LOCAL IP
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    return ip


# 📚 LOAD QUESTIONS
def load_questions():
    with open("question.txt", "r") as f:
        for line in f:
            if "|" in line:
                q, a = line.strip().split("|")
                questions.append({"question": q, "answer": a})


load_questions()


# 🌐 ROUTES
@app.route("/")
def index():
    return redirect(url_for("client"))


@app.route("/client", methods=["GET", "POST"])
def client():
    if request.method == "POST":
        session["name"] = request.form.get("name")
        return redirect(url_for("client_quiz"))
    return render_template("client.html")


@app.route("/client-quiz")
def client_quiz():
    return render_template("client_quiz.html", name=session.get("name", "Player"))


@app.route("/server")
def server_dashboard():
    return render_template("server.html")


# 👤 JOIN
@socketio.on("join_quiz")
def join(data):
    global current_question_index, quiz_running, quiz_completed_flag

    name = data.get("name", "Player")
    sid = request.sid

    with lock:
        scores[sid] = 0
        client_states[sid] = {
            "name": name,
            "current_q": -1
        }

    socketio.emit("client_joined", {"name": name, "score": 0}, namespace="/server")

    # START QUIZ ONLY ONCE
    if not quiz_running and not quiz_completed_flag:
        quiz_running = True
        socketio.start_background_task(run_quiz)

    # SEND CURRENT QUESTION IF RUNNING
    if current_question_index >= 0 and current_question_index < len(questions):
        q = questions[current_question_index]

        emit("all_clients_next", {
            "number": current_question_index + 1,
            "question": q["question"],
            "time_left": QUESTION_DURATION
        })

# 📝 ANSWER
@socketio.on("submit_answer")
def handle_answer(data):
    global answered_clients

    sid = request.sid
    ans = data.get("answer", "").lower().strip()

    if sid not in client_states:
        return

    # prevent multiple answers
    if sid in answered_clients:
        return

    user_q = client_states[sid]["current_q"]

    # if invalid question
    if user_q == -1 or user_q >= len(questions):
        return

    answered_clients.add(sid)

    correct = questions[user_q]["answer"].lower().strip()

    if ans == correct:
        scores[sid] += 1

    response = {
        "name": client_states[sid]["name"],
        "score": scores[sid]
    }

    socketio.emit("score_update", response)
    socketio.emit("score_update", response, namespace="/server")


# 🚀 START QUIZ
@socketio.on("start_quiz", namespace="/server")
def start_quiz():
    socketio.start_background_task(run_quiz)

def run_quiz():
    global current_question_index, answered_clients, quiz_running, quiz_completed_flag

    total = len(questions)

    for q_index in range(total):
        current_question_index = q_index
        answered_clients = set()

        q = questions[q_index]

        # ✅ SEND QUESTION TO ALL CLIENTS
        socketio.emit("all_clients_next", {
            "number": q_index + 1,
            "question": q["question"],
            "time_left": QUESTION_DURATION
        }, namespace="/")

        # ✅ VERY IMPORTANT: track question per user
        for sid in client_states:
            client_states[sid]["current_q"] = q_index

        # ⏱️ TIMER LOOP
        for _ in range(QUESTION_DURATION):
            socketio.sleep(1)

    # ✅ QUIZ COMPLETED
    socketio.emit("quiz_completed", {}, namespace="/")

    # ✅ RESET STATE
    current_question_index = -1
    answered_clients = set()
    quiz_running = False
    quiz_completed_flag = True
# ❌ DISCONNECT
@socketio.on("disconnect")
def disconnect():
    sid = request.sid

    if sid in client_states:
        name = client_states[sid]["name"]
        del client_states[sid]
        del scores[sid]

        socketio.emit("client_left", {"name": name}, namespace="/server")

# 🚀 MAIN (UNCHANGED)
if __name__ == "__main__":
    local_ip = get_local_ip()

    print("\n" + "="*50)
    print("QUIZ SERVER IS LIVE!")
    print(f"Admin Dashboard: http://{local_ip}:{WEB_PORT}/server")
    print(f" Player Join Link: http://{local_ip}:{WEB_PORT}/client")
    print(f" TLS TCP Port: {TLS_PORT} (For Python Clients)")
    print("="*50 + "\n")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain("cert.pem", "key.pem")

    socketio.run(app, host="0.0.0.0", port=WEB_PORT, debug=False)