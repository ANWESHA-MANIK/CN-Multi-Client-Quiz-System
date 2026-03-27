# =====================================================================
# client.py  —  TLS TCP Quiz Client (Terminal Mode)
#
# Yeh file Python terminal se quiz khelne ke liye hai.
# Browser nahi use karna? Bas yeh file chalao.
#
# Usage:
#   python client.py                  →  localhost se connect karo
#   python client.py 192.168.1.5      →  kisi aur machine se connect karo
#
# Protocol (server ke saath handshake):
#   S → "NAME"
#   C → username
#   S → "READY"
#   S → {"type":"question", ...}\n  (har question ke liye)
#   C → {"answer":"..."}\n
#   S → {"type":"end", ...}\n       (quiz khatam pe)
# =====================================================================

import socket
import ssl
import json
import threading
import sys


# ──────────────────────────────────────────
# Configuration
# Command line se IP lo, default localhost
# ──────────────────────────────────────────
SERVER_IP        = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT             = 5000   # app.py mein TLS_PORT ke barabar hona chahiye
QUESTION_TIMEOUT = 15     # Seconds — app.py ke QUESTION_DURATION ke barabar hona chahiye


def timed_input(prompt, timeout=15):
    """
    Time-limited input function.
    User ko sirf 'timeout' seconds milte hain answer dene ke liye.
    Agar waqt khatam toh empty string return kar do (auto-submit).

    Kaise kaam karta hai:
      - Daemon thread mein stdin.readline() call karo
      - Main thread t.join(timeout) se timeout tak wait karta hai
      - Thread abhi bhi alive hai = user ne kuch type nahi kiya = time out
    """
    print(prompt, end="", flush=True)
    answer = [None]   # List use karo kyunki thread closure mein assign karna hai

    def _read():
        try:
            answer[0] = sys.stdin.readline().strip()
        except Exception:
            answer[0] = ""

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(timeout)   # Itne seconds tak wait karo

    if t.is_alive():
        # Thread live hai = user ne enter nahi dabaya = time out
        print(f"\n  [!] Waqt khatam! Khali jawab submit ho raha hai...\n")
        return ""

    return answer[0] or ""


def print_separator(char="─", width=52):
    """Clean separator line print karo"""
    print(char * width)


def start_client():
    """
    Main client function.
    TLS connection banao → naam do → quiz khelo → result dekho.
    """
    # ──────────────────────────────────────────
    # TLS Context Setup
    # Client side SSL context — self-signed cert accept karta hai
    # check_hostname=False aur CERT_NONE isliye kyunki hum khud cert banate hain
    # Real production app mein verify_mode = CERT_REQUIRED hona chahiye
    # ──────────────────────────────────────────
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False       # Self-signed ke liye zaroori
    context.verify_mode   = ssl.CERT_NONE  # Certificate verify mat karo (project use)

    secure_socket = None

    try:
        print()
        print_separator("═")
        print("   CN PROJECT  ▸  QUIZ CLIENT (Terminal)")
        print_separator("═")
        print(f"   Server: {SERVER_IP}:{PORT}  (TLS Encrypted)")
        print_separator("═")
        print()

        # ── Step 1: Raw TCP socket banao ──
        raw_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_socket.settimeout(10)   # Connection attempt timeout: 10 seconds

        # ── Step 2: TCP socket ko TLS se wrap karo ──
        # Ab sab data encrypted rahega
        secure_socket = context.wrap_socket(raw_socket, server_hostname=SERVER_IP)

        print(f"  [*] Connect kar rahe hain {SERVER_IP}:{PORT} se...")
        secure_socket.connect((SERVER_IP, PORT))
        secure_socket.settimeout(None)   # Connected! Ab blocking mode mein jao
        print("  [+] Connected! (TLS Encryption Active)\n")

        # ──────────────────────────────────────────
        # Handshake Phase
        # Server pehle "NAME" bhejta hai
        # Hum naam bhejte hain
        # Server "READY" se confirm karta hai
        # ──────────────────────────────────────────

        # Server ka pehla signal receive karo
        signal = secure_socket.recv(1024).decode().strip()

        if signal == "NAME":
            name = input("  Apna naam daalo: ").strip()
            if not name:
                name = "Anonymous"
            secure_socket.sendall(name.encode())
        else:
            print(f"  [!] Unexpected signal from server: '{signal}'")
            return

        # READY signal ka wait karo
        ready = secure_socket.recv(1024).decode().strip()
        if ready != "READY":
            print(f"  [!] Expected READY, got: '{ready}'")
            return

        print(f"\n  [✓] {name} ke roop mein join kar liya!")
        print("  [...] Host ke quiz start karne ka intezaar karo...\n")

        # ──────────────────────────────────────────
        # Main Quiz Loop
        # TCP stream-based protocol:
        #   - Data fragments mein aa sakta hai
        #   - Buffer mein jodo aur newline pe split karo
        # ──────────────────────────────────────────
        buffer           = ""
        total_questions  = 0
        final_score      = 0

        while True:
            data = secure_socket.recv(4096).decode()

            if not data:
                # Server ne connection close kar di
                print("\n  [!] Server se connection toot gayi.")
                break

            buffer += data   # Received data buffer mein daalo

            # Jab bhi newline mile, ek complete message process karo
            while "\n" in buffer:
                message, buffer = buffer.split("\n", 1)
                message = message.strip()
                if not message:
                    continue   # Khali line skip karo

                try:
                    payload  = json.loads(message)
                    msg_type = payload.get("type", "")

                    # ── Naya question aaya ──
                    if msg_type == "question":
                        num             = payload.get("number", "?")
                        total_questions = payload.get("total", "?")
                        question_text   = payload.get("question", "(no question)")

                        print()
                        print_separator()
                        print(f"  QUESTION {num} / {total_questions}")
                        print_separator()
                        print(f"  {question_text}")
                        print_separator()

                        # Timed input — 15 second mein jawab do
                        user_answer = timed_input(f"  Jawab do ({QUESTION_TIMEOUT}s): ", QUESTION_TIMEOUT)

                        # Answer JSON format mein + newline delimiter ke saath bhejo
                        # Newline zaroori hai — server buffer.split("\n") se parse karta hai
                        answer_json = json.dumps({"answer": user_answer}) + "\n"
                        secure_socket.sendall(answer_json.encode())

                        print("  [✓] Jawab submit ho gaya! Agla question wait karo...\n")

                    # ── Quiz khatam ──
                    elif msg_type == "end":
                        final_score = payload.get("score", 0)
                        total_q     = payload.get("total", total_questions)

                        if isinstance(total_q, int) and total_q > 0:
                            pct = int((final_score / total_q) * 100)
                        else:
                            pct = 0

                        print()
                        print_separator("═")
                        print("   QUIZ COMPLETE!")
                        print_separator("═")
                        print(f"   Final Score  :  {final_score} / {total_q}")
                        print(f"   Percentage   :  {pct}%")

                        if pct == 100:
                            verdict = "PERFECT SCORE! Shabaash!"
                        elif pct >= 80:
                            verdict = "Bahut acha!"
                        elif pct >= 60:
                            verdict = "Pass! Theek hai."
                        else:
                            verdict = "Agli baar aur mehnat karo!"

                        print(f"   Result       :  {verdict}")
                        print_separator("═")
                        print()
                        return   # Quiz khatam — exit karo

                except json.JSONDecodeError:
                    # Partial ya invalid JSON — koi baat nahi, buffer mein aur data aayega
                    continue

    except ConnectionRefusedError:
        print(f"\n  [!] Connection refused.")
        print(f"      Server chal raha hai kya? ({SERVER_IP}:{PORT})")

    except socket.timeout:
        print(f"\n  [!] Connection timeout.")
        print(f"      Server reachable nahi hai: {SERVER_IP}:{PORT}")

    except KeyboardInterrupt:
        print("\n\n  [!] User ne quit kiya (Ctrl+C).")

    except Exception as e:
        print(f"\n  [!] Error: {e}")

    finally:
        if secure_socket:
            try:
                secure_socket.close()
            except Exception:
                pass
        print("  [*] Connection closed.\n")



if __name__ == "__main__":
    start_client()
