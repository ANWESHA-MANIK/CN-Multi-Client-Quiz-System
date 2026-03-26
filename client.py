import socket
import ssl
import json
import threading
import sys
import time

#Configuration - Use '127.0.0.1' for local or the Server's IP for LAN
SERVER_IP = "127.0.0.1"
PORT = 5000


# 🔥 NEW: timed input function
def timed_input(prompt, timeout=10):
    print(prompt, end="", flush=True)
    answer = [None]

    def get_input():
        answer[0] = sys.stdin.readline().strip()

    t = threading.Thread(target=get_input)
    t.daemon = True
    t.start()
    t.join(timeout)

    if t.is_alive():
        print("\n⏱️ Time's up! Auto-submitting...\n")
        return ""
    return answer[0]


def start_client():
    #1.Setup TLS Context (The Security Layer)
    #We use CERT_NONE and check_hostname=False because we are using 
    #self-signed certificates for this project.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    try:
        #2.Create a standard TCP Socket
        raw_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        #3.Wrap the socket with TLS (secure encrypted communication)
        secure_socket = context.wrap_socket(raw_socket, server_hostname=SERVER_IP)

        print(f"[*] Attempting to connect to {SERVER_IP}:{PORT}...")
        secure_socket.connect((SERVER_IP, PORT))
        print("[+] Connection Established (TLS Encrypted)\n")

        #4.Handle Authentication (Protocol Step: Server asks for 'NAME')
        server_signal = secure_socket.recv(1024).decode()
        if server_signal == "NAME":
            name = input("Enter your username to join: ")
            secure_socket.send(name.encode())

        #5.Wait for the 'READY' signal from server
        ready_signal = secure_socket.recv(1024).decode()
        if ready_signal == "READY":
            print("[!] Authenticated. Waiting for the host to start the quiz...")

        #Buffer to handle TCP stream (important fix for Deliverable 2)
        buffer = ""

        #6.Main Quiz Loop
        while True:
            # Receive data from server (TCP stream, not fixed messages)
            data = secure_socket.recv(4096).decode()

            if not data:
                print("[!] Connection lost.")
                break

            buffer += data  # accumulate data

            # Process complete messages using delimiter '\n'
            while "\n" in buffer:
                message, buffer = buffer.split("\n", 1)

                # Check for End of Quiz signal
                if message.startswith("END:"):
                    result = json.loads(message[4:])
                    print("\n" + "="*30)
                    print("       QUIZ COMPLETE")
                    print("="*30)
                    print(f" Final Score: {result['score']} / {result['total']}")
                    print("="*30)
                    return

                # Process Question Payload (JSON-based protocol)
                try:
                    payload = json.loads(message)
                    print(f"\n[Question] {payload['question']}")

                    # 🔥 CHANGED: timed input instead of blocking input
                    user_answer = timed_input("Your Answer (10s): ", 10)

                    # Send answer back as JSON + delimiter (important fix)
                    answer_payload = json.dumps({"answer": user_answer}) + "\n"
                    secure_socket.send(answer_payload.encode())

                    print("[*] Answer submitted. Waiting for next round...")

                except json.JSONDecodeError:
                    # Handles partial/invalid data safely
                    continue

    except Exception as e:
        print(f"[!] Networking Error: {e}")

    finally:
        secure_socket.close()
        print("\n[*] Socket Closed. Connection Terminated.")


if __name__ == "__main__":
    start_client()