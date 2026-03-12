import ssl
import socket
import threading
import json
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit
from collections import defaultdict

# iss jagah pe ham flask app koo initialize kar rahe hai
app = Flask(__name__)
app.secret_key = "quiz_secret_key"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', logger=True, engineio_logger=True)

#apna networking configurations yahi pe we are storing. 
HOST = "0.0.0.0"
TLS_PORT = 5000
WEB_PORT = 5001

# Global state
questions = []#questions se direct iss array me load karenge questions koo
current_question_index = 0#current active question hai jo bhi quiz me. will be updating as the quiz goes on
scores = defaultdict(int)
# client_states tracks: name, connection status, and the LAST question index they answered
client_states = {} 
lock = threading.Lock()#yea race conditions koo prevent karega. so that only one thread will modify the score during a race

#basic file handling se maine | se questions and answers koo strip kar diya and added them to the question array.
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
        #sabse pehela hadshake. yaha pe client sends their name to establish connection.        
        conn.send(b"NAME")
        name = conn.recv(1024).decode().strip()

        with lock:
            #after the successful handshake hamlog global me register karenge for the server.
            scores[client_id] = 0
            client_states[client_id] = {
                "name": name, 
                "connected": True, 
                "last_answered_idx": -1, #smary me move :) SECRETLY handled ra*** error.
                "is_tls": True #ensure karega ki handshake hoo chuka hai
            }
            # ek simple sa web socket jisse server UI update hoo jayega.
            socketio.emit("client_joined", {"name": name, "score": 0}, namespace="/server")

        conn.send(b"READY")#finally if all goes well then the client kaa balle balle

        last_sent_index = -1
        while True:
            #simple if else block hai... doing exactly what it reads to.
            while last_sent_index == current_question_index:
                if not client_states[client_id]["connected"]: return
                threading.Event().wait(0.2) 

            with lock:
                if current_question_index >= len(questions): break
                q_data = questions[current_question_index]
                active_idx = current_question_index
            
            #ab yaha pe actual communication hoo raha hai between client and server. 
            #now we will be sending the JSON as the payload over the secure tunnel that we establised earlier. 
            conn.send(json.dumps(q_data).encode())
            
            data = conn.recv(1024).decode()
            if not data: break
            
            try:
                ans_payload = json.loads(data)
                user_ans = ans_payload.get("answer", "").lower().strip()
                
                with lock:
                    #agar answer correct hai then we can lay back and enjoy. also yaha pe last answered index se check kr rhe hai ki unique hai ki nahi
                    if client_states[client_id]["last_answered_idx"] < active_idx:
                        correct_ans = q_data["answer"].lower().strip()
                        if user_ans == correct_ans:
                            scores[client_id] += 1
                        
                        client_states[client_id]["last_answered_idx"] = active_idx
                        
                        #again simple socket connection to update the UI
                        socketio.emit("score_update", {
                            "name": name, 
                            "score": scores[client_id], 
                            "question": active_idx + 1
                        }, namespace="/server")
                
                last_sent_index = active_idx
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

# Jab koi web client connect hota hai aur 'join_quiz' signal bhejta hai
@socketio.on("join_quiz")
def handle_join(data):
    name = data.get("name", "WebPlayer")
    sid = request.sid # Har connection ki unique ID (Socket ID)
    with lock:
        #what does it looks like to you?
        scores[sid] = 0
        client_states[sid] = {
            "name": name, 
            "connected": True, 
            "last_answered_idx": -1, 
            "is_socket": True
        }
        #aur ek transmission and coms b/w server and client telling that the client is ready
        socketio.emit("client_joined", {"name": name, "score": 0}, namespace="/server")
    
    #ab now lets develop logic for ki agar quiz beech mein hai, toh naye player ko current question bhej do
    if current_question_index < len(questions):
        emit("question", {
            "number": current_question_index + 1, 
            "question": questions[current_question_index]["question"]
        })

# Jab browser se koi answer submit karta hai
@socketio.on("submit_answer")
def handle_web_answer(data):
    sid = request.sid
    if sid not in client_states: return
    
    ans = data.get("answer", "").lower().strip()
    with lock:
        active_idx = current_question_index
        # Check karo ki kahin user purane question ka answer toh nahi de raha
        if client_states[sid]["last_answered_idx"] < active_idx:
            correct = questions[active_idx]["answer"].lower().strip()
            # Agar answer sahi hai toh score badhao
            if ans == correct:
                scores[sid] += 1

            # Record karo ki isne is question ka attempt khatam kar liya hai
            client_states[sid]["last_answered_idx"] = active_idx
            
            # stfu i know what comes next
            socketio.emit("score_update", {
                "name": client_states[sid]["name"], 
                "score": scores[sid], 
                "question": active_idx + 1
            }, namespace="/server")

# Ye event sirf Admin Dashboard se trigger hota hai 'Next' dabane par
@socketio.on("next_question", namespace="/server")
def trigger_next():
    global current_question_index
    with lock:
        # Check karo ki agla question list mein hai ya nahi
        if current_question_index < len(questions) - 1:
            current_question_index += 1
            # Sabhi web clients ko 'Next Question' ka signal aur data push karo
            socketio.emit("all_clients_next", {
                "number": current_question_index + 1,
                "question": questions[current_question_index]["question"]
            }, namespace="/")
            # Update Dashboard status
            socketio.emit("question_changed", {"current_question": current_question_index + 1}, namespace="/server")
        else:
            socketio.emit("result_all", namespace="/")

def start_tls_server():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain("cert.pem", "key.pem")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, TLS_PORT))
    server.listen(10)
    ssl_server = context.wrap_socket(server, server_side=True)
    
    count = 0
    while True:
        try:
            conn, addr = ssl_server.accept()
            count += 1
            threading.Thread(target=handle_tls_client, args=(conn, addr, f"tls_{count}"), daemon=True).start()
        except: break

threading.Thread(target=start_tls_server, daemon=True).start()

def get_local_ip():
    """
    Ye function aapke computer ka actual LAN IP dhoondhta hai.
    '8.8.8.8' (Google DNS) se ek dummy connection banakar hum check karte hain 
    ki humara data kis local IP se baahar ja raha hai.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Dummy connection, packet actually send nahi hota
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1' # Agar internet nahi hai toh localhost
    finally:
        s.close()
    return ip

# Jab koi base URL "/" pe aayega, usse seedha "/client" join page pe bhej do
@app.route("/")
def index(): return redirect(url_for("client"))

# Login Page: Yahan user apna naam enter karta hai
@app.route("/client", methods=["GET", "POST"])
def client():
    if request.method == "POST":
        # User ka naam session mein save kar lo taaki next page pe use ho sake
        session["name"] = request.form.get("name")
        return redirect(url_for("client_quiz"))
    # Host IP pass kar rahe hain UI ko display karne ke liye
    return render_template("client.html", server_ip=request.host.split(":")[0])

# Actual Quiz Page for Web Users
@app.route("/client-quiz")
def client_quiz():
    #another me move that makes me a absolute carnage
    if "name" not in session: return redirect(url_for("client"))
    return render_template("client_quiz.html", name=session["name"])

# don't except ki batau ki yaha kya karna hai
@app.route("/server")
def server_dashboard():
    return render_template("server.html")

if __name__ == "__main__":
    local_ip = get_local_ip()
    print("\n" + "="*50)
    print("🚀 QUIZ SERVER IS LIVE!")
    print(f"🔗 Admin Dashboard: http://{local_ip}:{WEB_PORT}/server")
    print(f"🔗 Player Join Link: http://{local_ip}:{WEB_PORT}/client")
    print(f"🛡️  TLS TCP Port: {TLS_PORT} (For Python Clients)")
    print("="*50 + "\n")
    
    # Bina debug mode ke run kar rahe hain taki threads sahi se chalein
    socketio.run(app, host="0.0.0.0", port=WEB_PORT, debug=False)