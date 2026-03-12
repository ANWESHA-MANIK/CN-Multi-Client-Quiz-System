### `CN-Multi-Client-Quiz-System`

# 🛡️ Secure Multi-Client Quiz System

A professional, real-time distributed quiz application demonstrating **Hybrid Networking Protocols**. This system bridges high-performance **TLS-secured TCP sockets** with modern **WebSockets (Socket.IO)** to create a seamless, cross-platform experience.

## 📡 Networking Features (Teacher's Guide)
* **Transport Layer Security (TLS 1.3):** Implements `ssl.SSLContext` to wrap TCP sockets, ensuring encrypted data transmission for Python clients.
* **Full-Duplex Communication:** Utilizes WebSockets via Flask-SocketIO for real-time, bi-directional server pushes to web clients.
* **Concurrent Programming:** Employs `threading` to handle multiple simultaneous TCP connections without blocking the main web server.
* **Application Layer Protocol:** Uses a custom JSON-based message format for structured communication between different client types.

---

## 🛠️ Setup & Installation

### 1. Prerequisite: Virtual Environment
It is highly recommended to run this in a virtual environment to keep your global Python installation clean.

**Windows:**
```bash
python -m venv venv
.\venv\Scripts\activate

```

**macOS/Linux:**

```bash
python3 -m venv venv
source venv/bin/activate

```

### 2. Install Dependencies

```bash
pip install flask flask-socketio eventlet

```

### 3. Generate Security Certificates

The TLS server requires a certificate and private key. You can generate self-signed ones for testing:

```bash
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -sha256 -days 365 -nodes

```

*Note: Ensure `cert.pem` and `key.pem` are in the project root folder.*

---

## 🚀 How to Run

### Step 1: Start the Central Server

The server hosts both the Web Dashboard and the TLS Socket listener.

```bash
python app.py

```

* **Web Dashboard:** `http://localhost:5001/server`
* **Web Quiz Portal:** `http://localhost:5001/client`

### Step 2: Connect Python Clients (Optional)

To demonstrate the raw TCP/TLS networking part of the project:

```bash
python client.py

```

### Step 3: Conduct the Quiz

1. Open the **Server Dashboard** in your browser.
2. Have students join via the **Web Portal** or the **Python Client**.
3. Click **"Push Next Question"** on the Dashboard. All clients will receive the question simultaneously.

---

## 📂 Project Structure

* `app.py`: The core engine managing TLS threads and SocketIO namespaces.
* `client.py`: Python client implementing the secure TLS socket connection.
* `question.txt`: The database for quiz content (Format: `Question|Answer`).
* `templates/`: High-end Glassmorphism UI for the web interface.
