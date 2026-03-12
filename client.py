import socket
import ssl
import json
import sys

SERVER_IP = "127.0.0.1"
PORT = 5000

context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
context.check_hostname = False
context.verify_mode = ssl.CERT_NONE

client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
ssl_client = context.wrap_socket(client, server_hostname=SERVER_IP)

ssl_client.connect((SERVER_IP, PORT))

print("Connected to Quiz Server (TLS Secured)")


def receive_exact(size=1024):
    data = b""
    while len(data) < size:
        chunk = ssl_client.recv(size - len(data))
        if not chunk:
            break
        data += chunk
    return data.decode()


name = input("Enter your name: ")
ssl_client.send(name.encode())

import time

time.sleep(0.3)

response = receive_exact(1024)
print(f"Response: {response}")

if "READY" in response:
    print("Ready to start!")
elif "NAME" in response:
    print("Server asked for name again, but continuing...")
    print("Ready to start!")
else:
    print(f"Note: Got response - {response}")

question_num = 1
data = ""

while True:
    try:
        data = receive_exact(4096)

        if not data:
            break

        if data.startswith("END:"):
            result = json.loads(data[4:])
            print(f"\nQuiz Complete!")
            print(f"Your Score: {result['score']} / {result['total']}")
            break

        if data == "NEXT":
            continue

        q_data = json.loads(data)

        print(f"\n--- Question {question_num} ---")
        print(f"Question: {q_data['question']}")

        answer = input("Your Answer: ")
        ssl_client.send(json.dumps({"answer": answer}).encode())

        time.sleep(0.2)

        question_num += 1

    except json.JSONDecodeError as e:
        print(f"JSON Error: {e}, data: {data}")
        break
    except Exception as e:
        print(f"Error: {e}")
        break

ssl_client.close()
print("Connection closed")
