import socket
import threading

HOST = "0.0.0.0"
PORT = 5000

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((HOST, PORT))
server.listen()

print("Server started. Waiting for clients...")

clients = []
scores = {}

def load_questions():
    questions = []
    with open("question.txt", "r") as f:
        for line in f:
            q, a = line.strip().split("|")
            questions.append((q, a))
    return questions

quiz_questions = load_questions()

def handle_client(conn, addr):
    print("Connected:", addr)

    name = conn.recv(1024).decode()
    scores[name] = 0

    for question, answer in quiz_questions:
        conn.send(question.encode())

        user_answer = conn.recv(1024).decode()

        if user_answer.lower() == answer.lower():
            scores[name] += 1

    result = f"Your Score: {scores[name]}"
    conn.send(result.encode())

    conn.close()

while True:
    conn, addr = server.accept()
    thread = threading.Thread(target=handle_client, args=(conn, addr))
    thread.start()