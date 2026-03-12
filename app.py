import ssl
import socket
import threading
import json
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit
from collections import defaultdict

app = Flask(__name__)
app.secret_key = "quiz_secret_key"
# Using '*' for cors allows local network testing easily
socketio = SocketIO(app, cors_allowed_origins="*")

HOST = "0.0.0.0"
TLS_PORT = 5000
WEB_PORT = 5001

# Global state
questions = []
current_question_index = 0
scores = defaultdict(int)
client_states = {}
lock = threading.Lock()

def load_questions():
    global questions
    questions = []
    try:
        with open("question.txt", "r") as f:
            for line in f:
                if "|" in line:
                    q, a = line.strip().split("|")
                    questions.append({"question": q, "answer": a})
    except FileNotFoundError:
        print("Error: question.txt not found!")

load_questions()

# --- TLS TCP SERVER LOGIC ---
def handle_tls_client(conn, addr, client_id):
    global current_question_index
    print(f"[*] TLS Client connected: {addr}")
    
    try:
        # Step 1: Request Name (Application Layer Protocol)
        conn.send(b"NAME")
        name = conn.recv(1024).decode().strip()

        with lock:
            scores[client_id] = 0
            client_states[client_id] = {
                "name": name, "connected": True, "current_q": -1, "is_tls": True
            }
            # Inform the Web Dashboard
            socketio.emit("client_joined", {"name": name, "score": 0}, namespace="/server")

        conn.send(b"READY")

        last_sent_index = -1
        while True:
            # Wait for the global question index to advance
            while last_sent_index == current_question_index:
                if not client_states[client_id]["connected"]: return
                threading.Event().wait(0.1) 

            with lock:
                if current_question_index >= len(questions): break
                q_data = questions[current_question_index]
            
            # Send question as JSON (Modern standard)
            conn.send(json.dumps(q_data).encode())
            
            # Receive Answer
            data = conn.recv(1024).decode()
            if not data: break
            
            try:
                ans_payload = json.loads(data)
                user_ans = ans_payload.get("answer", "").lower().strip()
                
                with lock:
                    if user_ans == q_data["answer"].lower().strip():
                        scores[client_id] += 1
                    
                    client_states[client_id]["current_q"] = current_question_index
                    last_sent_index = current_question_index
                    
                    # Live update to dashboard
                    socketio.emit("score_update", {
                        "name": name, 
                        "score": scores[client_id], 
                        "question": current_question_index + 1
                    }, namespace="/server")
            except:
                continue

        # Final Result
        res = json.dumps({"score": scores[client_id], "total": len(questions)})
        conn.send(f"END:{res}".encode())

    except Exception as e:
        print(f"[!] TLS Error: {e}")
    finally:
        with lock:
            if client_id in client_states: client_states[client_id]["connected"] = False
            socketio.emit("client_left", {"name": name}, namespace="/server")
        conn.close()

def start_tls_server():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain("cert.pem", "key.pem")
    
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, TLS_PORT))
    server.listen(10)
    
    ssl_server = context.wrap_socket(server, server_side=True)
    print(f"[*] Secure TLS Server listening on port {TLS_PORT}")

    count = 0
    while True:
        conn, addr = ssl_server.accept()
        count += 1
        threading.Thread(target=handle_tls_client, args=(conn, addr, f"tls_{count}"), daemon=True).start()

# Start background TLS networking
threading.Thread(target=start_tls_server, daemon=True).start()

# --- WEB/FLASK ROUTES ---
@app.route("/")
def index(): return redirect(url_for("client"))

@app.route("/client", methods=["GET", "POST"])
def client():
    if request.method == "POST":
        session["name"] = request.form.get("name")
        return redirect(url_for("client_quiz"))
    return render_template("client.html", server_ip=request.host.split(":")[0])

@app.route("/client-quiz")
def client_quiz():
    if "name" not in session: return redirect(url_for("client"))
    return render_template("client_quiz.html", name=session["name"])

@app.route("/server")
def server_dashboard():
    return render_template("server.html")

# --- SOCKET.IO EVENTS (Web Clients) ---
@socketio.on("join_quiz")
def handle_join(data):
    name = data.get("name", "WebPlayer")
    sid = request.sid
    with lock:
        scores[sid] = 0
        client_states[sid] = {"name": name, "connected": True, "current_q": -1, "is_socket": True}
        socketio.emit("client_joined", {"name": name, "score": 0}, namespace="/server")
    
    # Send current question if quiz is active
    if current_question_index < len(questions):
        emit("question", {"number": current_question_index + 1, "question": questions[current_question_index]["question"]})

@socketio.on("submit_answer")
def handle_web_answer(data):
    sid = request.sid
    if sid not in client_states: return
    
    ans = data.get("answer", "").lower().strip()
    with lock:
        correct = questions[current_question_index]["answer"].lower().strip()
        if ans == correct:
            scores[sid] += 1
        
        client_states[sid]["current_q"] = current_question_index
        socketio.emit("score_update", {
            "name": client_states[sid]["name"], 
            "score": scores[sid], 
            "question": current_question_index + 1
        }, namespace="/server")

@socketio.on("next_question", namespace="/server")
def trigger_next():
    global current_question_index
    with lock:
        if current_question_index < len(questions) - 1:
            current_question_index += 1
            # Push to all web clients
            socketio.emit("all_clients_next", {
                "number": current_question_index + 1,
                "question": questions[current_question_index]["question"]
            }, namespace="/")
            # Update Dashboard
            socketio.emit("question_changed", {"current_question": current_question_index + 1}, namespace="/server")
        else:
            # End Quiz for web clients
            socketio.emit("result_all", namespace="/")

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=WEB_PORT, debug=False)