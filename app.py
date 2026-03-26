import ssl
import socket
import threading
import time
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
quiz_start_time = None


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
    global quiz_start_time

    name = data.get("name", "Player")
    sid = request.sid

    with lock:
        scores[sid] = 0
        client_states[sid] = {"name": name}

    socketio.emit("client_joined", {"name": name, "score": 0}, namespace="/server")

    # 🔥 AUTO START IF FIRST USER
    if quiz_start_time is None:
        quiz_start_time = time.time()
        socketio.start_background_task(run_quiz)

    # 🔥 LATE JOIN SYNC
    elapsed = time.time() - quiz_start_time
    q_index = int(elapsed // QUESTION_DURATION)

    if q_index < len(questions):
        remaining = QUESTION_DURATION - (elapsed % QUESTION_DURATION)

        emit("all_clients_next", {
            "number": q_index + 1,
            "question": questions[q_index]["question"],
            "time_left": int(remaining)
        })


# 📝 ANSWER
@socketio.on("submit_answer")
def handle_answer(data):
    sid = request.sid
    ans = data.get("answer", "").lower().strip()

    if sid not in client_states or quiz_start_time is None:
        return

    elapsed = time.time() - quiz_start_time
    q_index = int(elapsed // QUESTION_DURATION)

    if q_index >= len(questions):
        return

    correct = questions[q_index]["answer"].lower().strip()

    if ans == correct:
        scores[sid] += 1

    response = {
        "name": client_states[sid]["name"],
        "score": scores[sid]
    }

    socketio.emit("score_update", response, namespace="/", broadcast=True)
    socketio.emit("score_update", response, namespace="/server", broadcast=True)


# 🚀 MANUAL START ALSO WORKS
@socketio.on("start_quiz", namespace="/server")
def start_quiz():
    global quiz_start_time

    quiz_start_time = time.time()
    socketio.start_background_task(run_quiz)


# ⏱️ AUTO QUIZ LOOP
def run_quiz():
    total = len(questions)

    for q_index in range(total):
        if quiz_start_time is None:
            break

        q = questions[q_index]

        #send question
        socketio.emit("all_clients_next", {
            "number": q_index + 1,
            "question": q["question"],
            "time_left": QUESTION_DURATION
        }, namespace="/")

        #wait EXACT duration
        socketio.sleep(QUESTION_DURATION)

    #after all questions
    socketio.emit("quiz_completed", {}, namespace="/")

# ❌ DISCONNECT
@socketio.on("disconnect")
def disconnect():
    sid = request.sid

    if sid in client_states:
        name = client_states[sid]["name"]
        del client_states[sid]
        del scores[sid]

        socketio.emit("client_left", {"name": name}, namespace="/server")

# 🚀 MAIN (UNCHANGED PRINTS)
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