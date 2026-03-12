import socket

SERVER_HOST = "127.0.0.1"   
SERVER_PORT = 5000          

def start_client():
    try:
        
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        print("Connecting to server...")
        client_socket.connect((SERVER_HOST, SERVER_PORT))
        print("Connected to quiz server!\n")

        while True:
            
            message = client_socket.recv(1024).decode()

            if not message:
                break

            
            if message.startswith("QUESTION"):
                print("\n" + message)

                answer = input("Enter your answer: ")
                client_socket.send(answer.encode())

            
            elif message.startswith("LEADERBOARD"):
                print("\nLeaderboard Update:")
                print(message)

            
            elif message.startswith("FINAL"):
                print("\nFinal Result:")
                print(message)
                break

            else:
                print(message)

        client_socket.close()
        print("\nConnection closed.")

    except ConnectionRefusedError:
        print("Error: Cannot connect to server. Is the server running?")
    except Exception as e:
        print("Error:", e)


if __name__ == "__main__":
    start_client()