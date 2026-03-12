import ssl
import socket
import threading
import json
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit
from collections import defaultdict

app = Flask(__name__)
app.secret_key = "quiz_secret_key"
socketio = SocketIO(app, cors_allowed_origins="*")

HOST = "0.0.0.0"
TLS_PORT = 5000
WEB_PORT = 5001

questions = []
current_question_index = 0
scores = defaultdict(int)
client_states = {}
lock = threading.Lock()


def load_questions():
    global questions
    with open("question.txt", "r") as f:
        for line in f:
            q, a = line.strip().split("|")
            questions.append({"question": q, "answer": a})


load_questions()


def handle_tls_client(conn, addr, client_id):
    global current_question_index
    print(f"TLS Client connected: {addr} ({client_id})")

    try:
        conn.send(b"NAME")
        name = conn.recv(1024).decode()

        with lock:
            scores[client_id] = 0
            client_states[client_id] = {
                "name": name,
                "connected": True,
                "current_q": 0,
                "is_tls": True,
            }
            socketio.emit(
                "client_joined", {"name": name, "score": 0}, namespace="/server"
            )

        conn.send(b"READY")

        while True:
            with lock:
                if current_question_index >= len(questions):
                    break
                q_data = questions[current_question_index]

            conn.send(json.dumps(q_data).encode())

            data = conn.recv(1024).decode()
            if not data:
                break

            answer_data = json.loads(data)

            with lock:
                is_correct = (
                    answer_data["answer"].lower().strip()
                    == q_data["answer"].lower().strip()
                )
                if is_correct:
                    scores[client_id] += 1
                client_states[client_id]["current_q"] = current_question_index + 1
                socketio.emit(
                    "score_update",
                    {
                        "name": name,
                        "score": scores[client_id],
                        "question": current_question_index + 1,
                    },
                    namespace="/server",
                )

            conn.send(b"NEXT")

            with lock:
                if current_question_index < len(questions):
                    all_answered = True
                    for cid, state in client_states.items():
                        if (
                            state.get("connected", False)
                            and state.get("current_q", 0) <= current_question_index
                        ):
                            all_answered = False
                            break
                    if all_answered:
                        current_question_index += 1

        final_score = scores[client_id]
        result = json.dumps({"score": final_score, "total": len(questions)})
        conn.send(f"END:{result}".encode())

    except Exception as e:
        print(f"Error with client {addr}: {e}")
    finally:
        with lock:
            if client_id in client_states:
                client_states[client_id]["connected"] = False
                socketio.emit(
                    "client_left",
                    {"name": client_states[client_id].get("name", "Unknown")},
                    namespace="/server",
                )
        conn.close()
        print(f"TLS Client disconnected: {addr}")


def start_tls_server():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain("cert.pem", "key.pem")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, TLS_PORT))
    server.listen(5)

    ssl_server = context.wrap_socket(server, server_side=True)
    print(f"Secure TLS Server started on port {TLS_PORT}")

    client_counter = 0
    while True:
        try:
            conn, addr = ssl_server.accept()
            client_counter += 1
            client_id = f"tls_client_{client_counter}"
            thread = threading.Thread(
                target=handle_tls_client, args=(conn, addr, client_id), daemon=True
            )
            thread.start()
        except Exception as e:
            print(f"Error accepting TLS connection: {e}")


tls_thread = threading.Thread(target=start_tls_server, daemon=True)
tls_thread.start()


@app.route("/")
def index():
    return redirect(url_for("client"))


@app.route("/client", methods=["GET", "POST"])
def client():
    if request.method == "POST":
        session["name"] = request.form.get("name")
        return redirect(url_for("client_quiz"))
    return render_template("client.html", server_ip=request.host.split(":")[0])


@app.route("/client-quiz")
def client_quiz():
    if "name" not in session:
        return redirect(url_for("client"))
    return render_template(
        "client_quiz.html", name=session["name"], server_ip=request.host.split(":")[0]
    )


@app.route("/server")
def server():
    return render_template("server.html")


@app.route("/api/scores")
def get_scores():
    with lock:
        data = {
            "scores": {
                client_states[cid]["name"]: scores[cid]
                for cid in client_states
                if client_states[cid].get("connected", False)
            },
            "current_question": current_question_index + 1
            if current_question_index < len(questions)
            else 0,
            "total_questions": len(questions),
        }
    return jsonify(data)


@app.route("/api/next-question", methods=["POST"])
def next_question():
    global current_question_index
    with lock:
        if current_question_index < len(questions) - 1:
            current_question_index += 1
    return jsonify({"success": True, "current_question": current_question_index + 1})


@socketio.on("connect")
def handle_connect():
    print(f"Client connected: {request.sid}")


@socketio.on("join_quiz")
def handle_join(data):
    name = data.get("name")
    if not name:
        name = session.get("name", f"Player_{request.sid[:8]}")

    with lock:
        scores[request.sid] = 0
        client_states[request.sid] = {
            "name": name,
            "connected": True,
            "current_q": 0,
            "is_socket": True,
        }
        socketio.emit("client_joined", {"name": name, "score": 0}, namespace="/server")

    if current_question_index < len(questions):
        emit(
            "question",
            {
                "number": current_question_index + 1,
                "question": questions[current_question_index]["question"],
            },
        )


@socketio.on("submit_answer")
def handle_answer(data):
    name = client_states.get(request.sid, {}).get("name", "Unknown")
    answer = data.get("answer", "")

    with lock:
        if current_question_index >= len(questions):
            emit("result", {"score": scores[request.sid], "total": len(questions)})
            return

        correct_answer = questions[current_question_index]["answer"]
        is_correct = answer.lower().strip() == correct_answer.lower().strip()

        if is_correct:
            scores[request.sid] += 1

        client_states[request.sid]["current_q"] = current_question_index + 1

        socketio.emit(
            "score_update",
            {
                "name": name,
                "score": scores[request.sid],
                "question": current_question_index + 1,
            },
            namespace="/server",
        )

        all_answered = True
        for cid, state in client_states.items():
            if (
                state.get("connected", False)
                and state.get("current_q", 0) <= current_question_index
            ):
                all_answered = False
                break

        if all_answered and current_question_index < len(questions) - 1:
            socketio.emit(
                "question_changed",
                {"current_question": current_question_index + 1},
                namespace="/server",
            )

        if current_question_index < len(questions) - 1:
            next_q_num = current_question_index + 1
            emit(
                "question",
                {
                    "number": next_q_num + 1,
                    "question": questions[next_q_num]["question"],
                },
            )
        else:
            emit("result", {"score": scores[request.sid], "total": len(questions)})


@socketio.on("disconnect")
def handle_disconnect():
    name = client_states.get(request.sid, {}).get("name", "Unknown")
    with lock:
        if request.sid in client_states:
            client_states[request.sid]["connected"] = False
            socketio.emit("client_left", {"name": name}, namespace="/server")


@socketio.on("next_question")
def handle_next_question():
    global current_question_index
    with lock:
        if current_question_index < len(questions) - 1:
            current_question_index += 1
            socketio.emit(
                "question_changed",
                {"current_question": current_question_index + 1},
                namespace="/server",
            )
            socketio.emit(
                "all_clients_next",
                {
                    "question": questions[current_question_index]["question"],
                    "number": current_question_index + 1,
                },
            )


if __name__ == "__main__":
    print(f"Starting Flask-SocketIO server on port {WEB_PORT}")
    print(f"TLS TCP server running on port {TLS_PORT}")
    socketio.run(app, host="0.0.0.0", port=WEB_PORT, debug=False, use_reloader=False)
