import socket
import ssl
import json
import time

# Configuration - Use '127.0.0.1' for local or the Server's IP for LAN
SERVER_IP = "127.0.0.1"
PORT = 5000

def start_client():
    # 1. Setup TLS Context (The Security Layer)
    # We use CERT_NONE and check_hostname=False because we are using 
    # self-signed certificates for this project.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    try:
        # 2. Create a standard TCP Socket
        raw_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        # 3. Wrap the socket with TLS
        secure_socket = context.wrap_socket(raw_socket, server_hostname=SERVER_IP)
        
        print(f"[*] Attempting to connect to {SERVER_IP}:{PORT}...")
        secure_socket.connect((SERVER_IP, PORT))
        print("[+] Connection Established (TLS 1.3 Encrypted)\n")

        # 4. Handle Authentication (Protocol Step: Server asks for 'NAME')
        server_signal = secure_socket.recv(1024).decode()
        if server_signal == "NAME":
            name = input("Enter your username to join: ")
            secure_socket.send(name.encode())

        # 5. Wait for the 'READY' signal
        ready_signal = secure_socket.recv(1024).decode()
        if ready_signal == "READY":
            print("[!] Authenticated. Waiting for the host to start the quiz...")

        # 6. Main Quiz Loop
        while True:
            # Receive data from server
            data = secure_socket.recv(4096).decode()
            
            if not data:
                print("[!] Connection lost.")
                break

            # Check for End of Quiz signal
            if data.startswith("END:"):
                result = json.loads(data[4:])
                print("\n" + "="*30)
                print("       QUIZ COMPLETE")
                print("="*30)
                print(f" Final Score: {result['score']} / {result['total']}")
                print("="*30)
                break

            # Process Question Payload
            try:
                payload = json.loads(data)
                print(f"\n[Question] {payload['question']}")
                
                user_answer = input("Your Answer: ")
                
                # Send answer back as JSON
                answer_payload = json.dumps({"answer": user_answer})
                secure_socket.send(answer_payload.encode())
                
                print("[*] Answer submitted. Waiting for next round...")

            except json.JSONDecodeError:
                # Sometimes signals like 'NEXT' might come through
                continue

    except Exception as e:
        print(f"[!] Networking Error: {e}")
    finally:
        secure_socket.close()
        print("\n[*] Socket Closed. Connection Terminated.")

if __name__ == "__main__":
    start_client()